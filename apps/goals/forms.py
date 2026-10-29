from decimal import Decimal

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.money.category_forms import COLORS
from apps.money.forms import AmountField, format_amount
from apps.money.icon_catalog import CATALOG

from apps.households.models import Currency
from apps.money.models import Account

from .models import Goal
from .services import LIVE, contribute

ACCOUNT = "account"
MANUAL = "manual"


class GoalForm(forms.ModelForm):
    mode = forms.ChoiceField(
        choices=[(ACCOUNT, _("Рахує рахунок")), (MANUAL, _("Вношу вручну"))], widget=forms.RadioSelect
    )
    target_amount = AmountField(label=_("Скільки потрібно"), min_value=Decimal("1"))
    monthly_amount = AmountField(label=_("Відкладати на місяць"), min_value=Decimal("1"), required=False)
    color_slot = forms.TypedChoiceField(coerce=int, choices=[(slot, slot) for slot in COLORS], required=False)
    icon = forms.CharField(max_length=40, required=False)
    account = forms.ModelChoiceField(queryset=None, required=False, empty_label=None)

    class Meta:
        model = Goal
        fields = ["name", "target_amount", "currency_code", "monthly_amount", "deadline", "account", "color_slot", "icon", "emoji"]
        widgets = {"deadline": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        error_messages = {"name": {"required": _("Вкажіть назву цілі.")}}

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        self.instance.household = household
        current = self.instance.account_id
        accounts = household.accounts.filter(is_archived=False) | household.accounts.filter(pk=current or 0)
        self.fields["account"].queryset = accounts.distinct()
        if self.instance.pk:
            self.initial["target_amount"] = format_amount(self.instance.target_amount)
            if self.instance.monthly_amount:
                self.initial["monthly_amount"] = format_amount(self.instance.monthly_amount)
            self.initial["mode"] = ACCOUNT if self.instance.account_id else MANUAL
            self.initial["currency_code"] = self.instance.currency
        else:
            self.initial.setdefault("currency_code", household.base_currency)
            self.initial.setdefault("mode", MANUAL)
            self.initial.setdefault("color_slot", 1)

    def color_options(self):
        selected = str(self["color_slot"].value() or "")
        return [{"slot": slot, "checked": str(slot) == selected} for slot in COLORS]

    def account_options(self):
        selected = str(self["account"].value() or "")
        return [{"object": a, "checked": str(a.pk) == selected} for a in self.fields["account"].queryset]

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean_icon(self):
        icon = self.cleaned_data["icon"]
        if icon in CATALOG or (icon and icon == self.instance.icon):
            return icon
        return ""

    def clean_emoji(self):
        emoji = self.cleaned_data["emoji"].strip()
        if any(char.isalnum() for char in emoji):
            raise forms.ValidationError(_("Тут можна лише емодзі."))
        return emoji

    def currency_options(self):
        selected = self["currency_code"].value() or self.household.base_currency
        return [{"code": code, "checked": code == selected} for code, _label in Currency.choices]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("deadline"):
            cleaned["monthly_amount"] = None
        if cleaned.get("mode") != ACCOUNT:
            cleaned["account"] = None
            if cleaned.get("currency_code") == self.household.base_currency:
                cleaned["currency_code"] = ""
            return cleaned
        cleaned["currency_code"] = ""
        account = cleaned.get("account")
        if account is None:
            self.add_error("account", _("Оберіть рахунок, який рахуватиме ціль."))
            return cleaned
        taken = Goal.objects.filter(account=account, is_archived=False).exclude(pk=self.instance.pk).first()
        if taken:
            self.add_error("account", _("Цей рахунок уже рахує ціль «%(name)s».") % {"name": taken.name})
        return cleaned

    def save(self, commit=True):
        goal = super().save(commit=False)
        goal.color_slot = goal.color_slot or 1
        if commit:
            goal.save()
        return goal


class ContributionForm(forms.Form):
    IN = "in"
    OUT = "out"

    direction = forms.ChoiceField(
        choices=[(IN, _("Відклав")), (OUT, _("Взяв"))], widget=forms.RadioSelect, initial=IN
    )
    amount = AmountField(label=_("Сума"), min_value=Decimal("0.01"))
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    source = forms.ModelChoiceField(queryset=None, required=False, empty_label=None)
    member = forms.ModelChoiceField(queryset=None, required=False, empty_label=None)
    note = forms.CharField(
        max_length=200, required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Нотатка, необов'язково"), "autocomplete": "off"}),
    )

    def __init__(self, *args, goal, membership=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.goal = goal
        household = goal.household
        self.fields["member"].queryset = household.memberships.active().select_related("user")
        live = household.accounts.filter(is_archived=False, kind__in=LIVE)
        if goal.account_id:
            live = live.exclude(pk=goal.account_id)
        self.fields["source"].queryset = live
        self.initial.setdefault("date", timezone.localdate())
        if membership:
            self.initial.setdefault("member", membership.pk)
            mine = live.filter(owner=membership, kind=Account.Kind.CARD).first()
            if mine or goal.tracks_account:
                self.initial.setdefault("source", (mine or live.first()).pk if (mine or live.first()) else None)

    def member_options(self):
        selected = str(self["member"].value() or "")
        return [{"object": m, "checked": str(m.pk) == selected} for m in self.fields["member"].queryset]

    def source_options(self):
        selected = str(self["source"].value() or "")
        return [{"object": a, "checked": str(a.pk) == selected} for a in self.fields["source"].queryset]

    def clean(self):
        cleaned = super().clean()
        if self.goal.tracks_account and not cleaned.get("source"):
            self.add_error("source", _("Оберіть рахунок, з якого відкладаєте."))
        return cleaned

    def save(self):
        data = self.cleaned_data
        return contribute(
            self.goal,
            amount=data["amount"],
            taking=data["direction"] == self.OUT,
            on_date=data["date"],
            member=data.get("member"),
            note=data.get("note", ""),
            source=data.get("source"),
        )
