import datetime
from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Account, AccountValuation, Category, Transaction


def month_start(value):
    try:
        return datetime.datetime.strptime(value or "", "%Y-%m").date()
    except ValueError:
        return timezone.localdate().replace(day=1)


def next_month(month):
    return (month + datetime.timedelta(days=32)).replace(day=1)


class AmountField(forms.DecimalField):
    def __init__(self, **kwargs):
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("localize", True)
        kwargs.setdefault(
            "widget", forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off", "placeholder": "0"})
        )
        super().__init__(**kwargs)

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
        return super().to_python(value)


class TransactionFilterForm(forms.Form):
    SHARED = "shared"
    TYPE_CHOICES = [
        ("", _("Усі")),
        (Transaction.Type.EXPENSE, _("Витрати")),
        (Transaction.Type.INCOME, _("Доходи")),
        (Transaction.Type.TRANSFER, _("Перекази")),
    ]

    month = forms.CharField(required=False, widget=forms.HiddenInput)
    day = forms.IntegerField(required=False, min_value=1, max_value=31, widget=forms.HiddenInput)
    q = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": _("Пошук за назвою"), "autocomplete": "off", "type": "search"}),
    )
    type = forms.ChoiceField(required=False, choices=TYPE_CHOICES, widget=forms.RadioSelect)
    category = forms.TypedChoiceField(required=False, coerce=int, empty_value=None)
    member = forms.ChoiceField(required=False)
    account = forms.TypedChoiceField(required=False, coerce=int, empty_value=None)

    def __init__(self, data, household):
        super().__init__(data)
        self.categories = list(household.categories.filter(is_archived=False))
        self.members = list(household.memberships.select_related("user"))
        self.accounts = list(household.accounts.filter(is_archived=False))
        self.fields["category"].choices = [("", "")] + [(c.pk, c.name) for c in self.categories]
        self.fields["member"].choices = [("", ""), (self.SHARED, "")] + [(str(m.pk), m.user.name) for m in self.members]
        self.fields["account"].choices = [("", "")] + [(a.pk, a.name) for a in self.accounts]

    def clean_month(self):
        return month_start(self.cleaned_data["month"])

    def selected_day(self):
        month = self.cleaned_data["month"]
        day = self.cleaned_data.get("day")
        if not day:
            return None
        try:
            return month.replace(day=day)
        except ValueError:
            return None

    def filter(self, queryset, by_day=True):
        data = self.cleaned_data
        month = data.get("month") or month_start(None)
        queryset = queryset.filter(date__gte=month, date__lt=next_month(month))
        if by_day and self.selected_day():
            queryset = queryset.filter(date=self.selected_day())

        if data.get("q"):
            queryset = queryset.filter(self.search_query(data["q"]))
        if data.get("type"):
            queryset = queryset.filter(type=data["type"])
        if data.get("category"):
            queryset = queryset.filter(category_id=data["category"])
        if data.get("member") == self.SHARED:
            queryset = queryset.filter(member__isnull=True)
        elif data.get("member"):
            queryset = queryset.filter(member_id=data["member"])
        if data.get("account"):
            queryset = queryset.filter(Q(account_id=data["account"]) | Q(to_account_id=data["account"]))
        return queryset

    @staticmethod
    def search_query(text):
        # SQLite compares Cyrillic case-sensitively, so try the common spellings too
        text = text.strip()
        query = Q()
        for variant in {text, text.lower(), text.capitalize()}:
            query |= Q(title__icontains=variant) | Q(note__icontains=variant)
        return query

    def menus(self):
        category = self.cleaned_data.get("category")
        member = self.cleaned_data.get("member") or ""
        account = self.cleaned_data.get("account")

        category_options = [option("", _("Усі категорії"), not category)]
        for kind, heading in ((Category.Kind.EXPENSE, _("Витрати")), (Category.Kind.INCOME, _("Доходи"))):
            category_options.append({"heading": heading})
            category_options += [
                option(c.pk, c.name, c.pk == category, icon=c.icon, tone=c.color_slot)
                for c in self.categories
                if c.kind == kind
            ]

        member_options = [
            option("", _("Усі люди"), not member),
            option(self.SHARED, _("Спільне"), member == self.SHARED, initial="С", color="shared"),
            *[
                option(m.pk, m.user.name, str(m.pk) == member, initial=m.user.initial, color=m.color_slot)
                for m in self.members
            ],
        ]
        account_options = [
            option("", _("Усі рахунки"), not account),
            *[option(a.pk, a.name, a.pk == account, icon=a.icon, tone=0) for a in self.accounts],
        ]

        return [
            menu("category", "category", _("Категорія"), category_options),
            menu("member", "user", _("Хто платив"), member_options),
            menu("account", "credit-card", _("Рахунок"), account_options, align="end"),
        ]


def option(value, label, checked, **extra):
    return {"value": value, "label": label, "checked": checked, **extra}


def menu(name, icon, placeholder, options, align="start"):
    selected = next((o for o in options if o.get("checked") and o["value"] != ""), None)
    return {
        "name": name,
        "icon": icon,
        "placeholder": placeholder,
        "label": selected["label"] if selected else "",
        "options": options,
        "align": align,
    }


class TransactionForm(forms.ModelForm):
    WHEN_CHOICES = [("today", _("Сьогодні")), ("yesterday", _("Вчора")), ("other", _("Інша дата"))]

    when = forms.ChoiceField(choices=WHEN_CHOICES, widget=forms.RadioSelect, required=False)
    amount = AmountField(
        label=_("Сума"),
        min_value=Decimal("0.01"),
        error_messages={"min_value": _("Вкажіть суму більше нуля.")},
    )
    to_amount = AmountField(label=_("Зараховано"), required=False, min_value=Decimal("0.01"))
    member = forms.ModelChoiceField(queryset=None, required=False, empty_label=None)

    class Meta:
        model = Transaction
        fields = ["type", "amount", "title", "category", "account", "to_account", "to_amount", "member", "date", "note"]
        widgets = {
            "type": forms.RadioSelect,
            "title": forms.TextInput(attrs={"placeholder": _("Наприклад, Сільпо"), "autocomplete": "off"}),
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={"rows": 2, "placeholder": _("Нотатка, необов'язково")}),
        }
        error_messages = {
            "title": {"required": _("Вкажіть назву, наприклад «Сільпо».")},
            "account": {"required": _("Оберіть рахунок.")},
        }

    def __init__(self, *args, household, membership, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.household = household
        self.fields["category"].queryset = household.categories.filter(is_archived=False)
        self.fields["account"].queryset = household.accounts.filter(is_archived=False)
        self.fields["to_account"].queryset = household.accounts.filter(is_archived=False)
        self.fields["member"].queryset = household.memberships.active().select_related("user")

        self.fields["date"].required = False

        if self.instance.pk:
            self.initial["amount"] = format_amount(self.instance.amount)
            self.initial["when"] = when_for(self.instance.date)
            if self.instance.to_amount and self.instance.to_amount != self.instance.amount:
                self.initial["to_amount"] = format_amount(self.instance.to_amount)
            else:
                self.initial["to_amount"] = ""
        else:
            self.initial.setdefault("member", membership)
            self.initial.setdefault("account", default_account(household, membership))
            self.initial["when"] = "today"

    def clean(self):
        cleaned = super().clean()
        today = timezone.localdate()
        when = cleaned.get("when") or "other"
        if when == "today":
            cleaned["date"] = today
        elif when == "yesterday":
            cleaned["date"] = today - datetime.timedelta(days=1)
        elif not cleaned.get("date"):
            self.add_error("date", _("Оберіть дату."))

        category = cleaned.get("category")
        if category and category.kind != cleaned.get("type"):
            cleaned["category"] = None

        if cleaned.get("type") == Transaction.Type.TRANSFER:
            cleaned["category"] = None
            self.instance.category = None
        else:
            cleaned["to_account"] = None
            cleaned["to_amount"] = None
            self.instance.to_account = None
        return cleaned

    def save(self, commit=True):
        if self.instance.pk and {"date", "account"} & set(self.changed_data):
            self.instance.rate = None
        return super().save(commit)

    def category_options(self):
        return self.pills("category")

    def account_options(self):
        return self.pills("account")

    def to_account_options(self):
        return self.pills("to_account")

    def member_options(self):
        return self.pills("member")

    def pills(self, name):
        selected = str(self[name].value() or "")
        return [{"object": obj, "checked": str(obj.pk) == selected} for obj in self.fields[name].queryset]


def when_for(date):
    today = timezone.localdate()
    if date == today:
        return "today"
    if date == today - datetime.timedelta(days=1):
        return "yesterday"
    return "other"


def format_amount(value):
    text = f"{value:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def default_account(household, membership):
    accounts = household.accounts.filter(is_archived=False)
    cards = accounts.filter(kind=Account.Kind.CARD)
    return cards.filter(owner=membership).first() or cards.first() or accounts.first()


class AccountForm(forms.ModelForm):
    opening_balance = AmountField(label=_("Початковий залишок"), required=False)
    owner = forms.ModelChoiceField(queryset=None, required=False, empty_label=None)

    class Meta:
        model = Account
        fields = ["name", "kind", "investment_type", "currency", "owner", "opening_balance"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": _("Наприклад, Монобанк"), "autocomplete": "off"}),
            "kind": forms.RadioSelect,
            "investment_type": forms.RadioSelect,
            "currency": forms.RadioSelect,
        }
        error_messages = {"name": {"required": _("Вкажіть назву рахунку.")}}

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.household = household
        self.fields["owner"].queryset = household.memberships.active().select_related("user")
        self.fields["investment_type"].choices = Account.InvestmentType.choices
        if self.instance.pk:
            self.initial["opening_balance"] = format_amount(self.instance.opening_balance)
            if self.instance.transactions.exists() or self.instance.incoming_transfers.exists():
                self.fields["currency"].disabled = True

    def clean_opening_balance(self):
        return self.cleaned_data["opening_balance"] or Decimal("0")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") != Account.Kind.INVESTMENT:
            cleaned["investment_type"] = ""
        elif not cleaned.get("investment_type"):
            cleaned["investment_type"] = Account.InvestmentType.OTHER
        return cleaned

    def owner_options(self):
        selected = str(self["owner"].value() or "")
        return [{"object": m, "checked": str(m.pk) == selected} for m in self.fields["owner"].queryset]


class ValuationForm(forms.ModelForm):
    value = AmountField(label=_("Поточна вартість"), min_value=Decimal("0"))

    class Meta:
        model = AccountValuation
        fields = ["value", "date"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, account, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.account = account
        self.initial.setdefault("date", timezone.localdate())

    def save(self, commit=True):
        valuation, created = AccountValuation.objects.update_or_create(
            account=self.instance.account,
            date=self.cleaned_data["date"],
            defaults={"value": self.cleaned_data["value"]},
        )
        return valuation

    def validate_unique(self):
        pass
