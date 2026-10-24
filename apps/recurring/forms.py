from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.households.models import Currency
from apps.money.forms import AmountField, default_account, format_amount
from apps.money.models import Account, Transaction
from apps.money.rates import RateNotFound

from .models import RecurringPayment
from .services import first_date_from


class PaymentForm(forms.ModelForm):
    amount = AmountField(label=_("Сума"), min_value=1)
    member = forms.ModelChoiceField(queryset=None, required=False, empty_label=None)
    reminders = forms.TypedMultipleChoiceField(
        choices=RecurringPayment.REMIND_CHOICES, coerce=int, required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = RecurringPayment
        fields = [
            "type", "title", "amount", "currency", "is_approximate", "account", "category", "member",
            "period", "start_date", "mode", "reminders",
        ]
        widgets = {
            "type": forms.RadioSelect,
            "title": forms.TextInput(attrs={"placeholder": _("Наприклад, Інтернет"), "autocomplete": "off"}),
            "period": forms.RadioSelect,
            "mode": forms.RadioSelect,
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
        error_messages = {
            "title": {"required": _("Вкажіть назву платежу.")},
            "account": {"required": _("Оберіть рахунок.")},
            "category": {"required": _("Оберіть категорію.")},
        }

    def __init__(self, *args, household, membership=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.household = household
        current = Q(pk=self.instance.category_id) if self.instance.category_id else Q(pk__in=[])
        self.fields["category"].queryset = household.categories.filter(Q(is_archived=False) | current)
        self.fields["account"].queryset = household.accounts.filter(is_archived=False).exclude(kind=Account.Kind.INVESTMENT)
        self.fields["member"].queryset = household.memberships.active().select_related("user")
        self.fields["mode"].required = False
        self.fields["type"].choices = [(Transaction.Type.EXPENSE, _("Витрата")), (Transaction.Type.INCOME, _("Дохід"))]
        if self.instance.pk:
            self.initial["amount"] = format_amount(self.instance.amount)
            self.initial["currency"] = self.instance.pay_currency
        else:
            self.initial.setdefault("reminders", self.instance.reminders)
            self.initial.setdefault("start_date", timezone.localdate())
            account = default_account(household, membership)
            if account:
                self.initial.setdefault("account", account.pk)
            if membership:
                self.initial.setdefault("member", membership.pk)

    def clean_mode(self):
        return self.cleaned_data.get("mode") or RecurringPayment.Mode.AUTO

    def clean(self):
        cleaned = super().clean()
        account = cleaned.get("account")
        if account and cleaned.get("currency") == account.currency:
            cleaned["currency"] = ""
        return cleaned

    def clean_reminders(self):
        return sorted(set(self.cleaned_data.get("reminders") or []), reverse=True)

    def currency_options(self):
        account = self.fields["account"].queryset.filter(pk=self["account"].value() or None).first()
        selected = self["currency"].value() or (account.currency if account else "UAH")
        return [{"code": code, "label": label, "checked": code == selected} for code, label in Currency.choices]

    def reminder_options(self):
        selected = {int(value) for value in (self["reminders"].value() or []) if str(value).isdigit()}
        return [{"value": value, "label": label, "checked": value in selected} for value, label in RecurringPayment.REMIND_CHOICES]

    def options(self, name):
        selected = str(self[name].value() or "")
        return [{"object": obj, "checked": str(obj.pk) == selected} for obj in self.fields[name].queryset]

    def account_options(self):
        return self.options("account")

    def category_options(self):
        return self.options("category")

    def member_options(self):
        return self.options("member")

    def save(self, commit=True):
        payment = super().save(commit=False)
        if "start_date" in self.changed_data or not payment.pk:
            payment.next_date = first_date_from(payment, timezone.localdate())
        if commit:
            payment.save()
        return payment


class PayForm(forms.Form):
    amount = AmountField(label=_("Сума"), min_value=Decimal("0.01"))
    date = forms.DateField(label=_("Дата"), widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, payment, **kwargs):
        super().__init__(*args, **kwargs)
        self.payment = payment
        try:
            amount = payment.account_amount(timezone.localdate())
        except RateNotFound:
            amount = payment.amount
        self.initial.setdefault("amount", format_amount(amount))
        self.initial.setdefault("date", timezone.localdate())
