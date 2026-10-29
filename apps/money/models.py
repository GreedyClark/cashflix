from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.households.models import Currency, Household, Membership

from .rates import convert_rate

CENT = Decimal("0.01")
MONEY = {"max_digits": 14, "decimal_places": 2}


class ExchangeRate(models.Model):
    currency = models.CharField(_("валюта"), max_length=3, choices=Currency.choices)
    date = models.DateField(_("дата"))
    rate = models.DecimalField(_("курс до гривні"), max_digits=14, decimal_places=6)

    class Meta:
        verbose_name = _("курс валюти")
        verbose_name_plural = _("курси валют")
        ordering = ["-date", "currency"]
        constraints = [
            models.UniqueConstraint(fields=["currency", "date"], name="unique_rate_per_day"),
        ]

    def __str__(self):
        return f"{self.currency} {self.date}: {self.rate}"


class Category(models.Model):
    OTHER_COLOR = 0

    class Kind(models.TextChoices):
        EXPENSE = "expense", _("витрата")
        INCOME = "income", _("дохід")

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="categories", verbose_name=_("сім'я")
    )
    name = models.CharField(_("назва"), max_length=50)
    kind = models.CharField(_("тип"), max_length=10, choices=Kind.choices, default=Kind.EXPENSE)
    icon = models.CharField(_("іконка"), max_length=40, blank=True, default="dots")
    emoji = models.CharField(_("емодзі"), max_length=16, blank=True)
    color_slot = models.PositiveSmallIntegerField(_("колір"), default=OTHER_COLOR)
    order = models.PositiveSmallIntegerField(_("порядок"), default=0)
    is_archived = models.BooleanField(_("в архіві"), default=False)

    class Meta:
        verbose_name = _("категорія")
        verbose_name_plural = _("категорії")
        ordering = ["kind", "order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["household", "kind", "name"], name="unique_category_name"),
        ]

    def __str__(self):
        return self.name

    @property
    def letter(self):
        return self.name[:1].upper()

    @property
    def color_var(self):
        return "--cat-other" if self.color_slot == self.OTHER_COLOR else f"--cat-{self.color_slot}"


def _sum_for_account(queryset, account_field, amount_field):
    total = queryset.order_by().values(account_field).annotate(total=Sum(amount_field)).values("total")
    zero = Value(Decimal("0"), output_field=DecimalField(**MONEY))
    return Coalesce(Subquery(total, output_field=DecimalField(**MONEY)), zero)


class AccountQuerySet(models.QuerySet):
    def with_balance(self):
        own = Transaction.objects.filter(account=OuterRef("pk"))
        incoming = Transaction.objects.filter(to_account=OuterRef("pk"), type=Transaction.Type.TRANSFER)

        return self.annotate(
            balance=F("opening_balance")
            + _sum_for_account(own.filter(type=Transaction.Type.INCOME), "account", "amount")
            - _sum_for_account(own.filter(type=Transaction.Type.EXPENSE), "account", "amount")
            - _sum_for_account(own.filter(type=Transaction.Type.TRANSFER), "account", "amount")
            + _sum_for_account(incoming, "to_account", "to_amount")
        )


class Account(models.Model):
    class Kind(models.TextChoices):
        CARD = "card", _("картка")
        CASH = "cash", _("готівка")
        SAVINGS = "savings", _("накопичувальний")
        INVESTMENT = "investment", _("інвестиційний")

    class YieldMode(models.TextChoices):
        FIXED = "fixed", _("під відсоток")
        MARKET = "market", _("ринкова вартість")

    class Payout(models.TextChoices):
        MONTHLY = "monthly", _("щомісяця")
        END = "end", _("в кінці терміну")
        CAPITALIZE = "capitalize", _("капіталізація")

    ICONS = {"card": "credit-card", "cash": "cash", "savings": "pig-money", "investment": "chart-line"}

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="accounts", verbose_name=_("сім'я")
    )
    name = models.CharField(_("назва"), max_length=50)
    kind = models.CharField(_("тип"), max_length=12, choices=Kind.choices, default=Kind.CARD)
    investment_type = models.CharField(_("куди інвестуєте"), max_length=60, blank=True)
    yield_mode = models.CharField(_("дохідність"), max_length=10, choices=YieldMode.choices, blank=True)
    annual_rate = models.DecimalField(_("ставка, % річних"), max_digits=5, decimal_places=2, null=True, blank=True)
    starts_on = models.DateField(_("дата початку"), null=True, blank=True)
    ends_on = models.DateField(_("дата закінчення"), null=True, blank=True)
    payout = models.CharField(_("виплата доходу"), max_length=10, choices=Payout.choices, blank=True)
    currency = models.CharField(_("валюта"), max_length=3, choices=Currency.choices, default=Currency.UAH)
    owner = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accounts",
        verbose_name=_("власник"),
        help_text=_("Порожньо — спільний рахунок"),
    )
    opening_balance = models.DecimalField(_("початковий залишок"), default=Decimal("0"), **MONEY)
    is_archived = models.BooleanField(_("в архіві"), default=False)
    created_at = models.DateTimeField(_("створено"), auto_now_add=True)

    objects = AccountQuerySet.as_manager()

    class Meta:
        verbose_name = _("рахунок")
        verbose_name_plural = _("рахунки")
        ordering = ["is_archived", "name"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.owner_id and self.owner.household_id != self.household_id:
            raise ValidationError({"owner": _("Власник має бути учасником цієї сім'ї.")})

    @property
    def icon(self):
        return self.ICONS[self.kind]

    @property
    def is_investment(self):
        return self.kind == self.Kind.INVESTMENT

    @property
    def is_fixed_income(self):
        return self.is_investment and self.yield_mode == self.YieldMode.FIXED

    def get_balance(self):
        return Account.objects.with_balance().get(pk=self.pk).balance


class AccountValuation(models.Model):
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="valuations", verbose_name=_("рахунок")
    )
    date = models.DateField(_("дата"), default=timezone.localdate)
    value = models.DecimalField(_("вартість"), **MONEY)
    created_at = models.DateTimeField(_("створено"), auto_now_add=True)

    class Meta:
        verbose_name = _("оцінка вартості")
        verbose_name_plural = _("оцінки вартості")
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["account", "date"], name="unique_valuation_per_day"),
            models.CheckConstraint(condition=Q(value__gte=0), name="valuation_value_not_negative"),
        ]

    def __str__(self):
        return f"{self.account}: {self.value} ({self.date})"


class TransactionQuerySet(models.QuerySet):
    def expenses(self):
        return self.filter(type=Transaction.Type.EXPENSE)

    def incomes(self):
        return self.filter(type=Transaction.Type.INCOME)

    def between(self, start, end):
        return self.filter(date__gte=start, date__lte=end)

    def total_base(self):
        return self.aggregate(total=Coalesce(Sum("amount_base"), Decimal("0")))["total"]


class Transaction(models.Model):
    class Type(models.TextChoices):
        EXPENSE = "expense", _("витрата")
        INCOME = "income", _("дохід")
        TRANSFER = "transfer", _("переказ")

    class Source(models.TextChoices):
        MANUAL = "manual", _("вручну")
        SHORTCUT = "shortcut", _("шорткат")
        RECURRING = "recurring", _("регулярний платіж")
        IMPORT = "import", _("імпорт")
        MONOBANK = "monobank", _("Monobank")

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="transactions", verbose_name=_("сім'я")
    )
    type = models.CharField(_("тип"), max_length=10, choices=Type.choices, default=Type.EXPENSE)
    date = models.DateField(_("дата"), default=timezone.localdate)
    title = models.CharField(_("назва"), max_length=120)
    note = models.TextField(_("нотатка"), blank=True)

    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="transactions", verbose_name=_("рахунок")
    )
    amount = models.DecimalField(_("сума"), **MONEY)
    currency = models.CharField(_("валюта"), max_length=3, choices=Currency.choices, editable=False)
    rate = models.DecimalField(_("курс"), max_digits=14, decimal_places=6, editable=False)
    amount_base = models.DecimalField(_("сума в основній валюті"), editable=False, **MONEY)

    to_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_transfers",
        verbose_name=_("на рахунок"),
    )
    to_amount = models.DecimalField(
        _("зараховано"),
        null=True,
        blank=True,
        help_text=_("Для переказу між валютами. Порожньо — та сама сума"),
        **MONEY,
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name=_("категорія"),
    )
    member = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name=_("хто"),
        help_text=_("Порожньо — спільне"),
    )

    source = models.CharField(_("джерело"), max_length=10, choices=Source.choices, default=Source.MANUAL)
    external_id = models.CharField(_("зовнішній id"), max_length=64, blank=True)
    occurred_at = models.DateTimeField(_("час операції"), null=True, blank=True)
    needs_review = models.BooleanField(_("перевірити категорію"), default=False)
    duplicate_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("можливий дубль"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("додав"),
    )
    created_at = models.DateTimeField(_("створено"), auto_now_add=True)

    objects = TransactionQuerySet.as_manager()

    class Meta:
        verbose_name = _("операція")
        verbose_name_plural = _("операції")
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["household", "date"]),
            models.Index(fields=["household", "type", "date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0) | Q(type="expense", amount__lt=0),
                name="transaction_amount_positive_or_refund",
            ),
            models.UniqueConstraint(
                fields=["household", "source", "external_id"],
                condition=~Q(external_id=""),
                name="unique_external_transaction",
            ),
        ]

    def __str__(self):
        return f"{self.date} {self.title} {self.amount} {self.currency}"

    @property
    def is_transfer(self):
        return self.type == self.Type.TRANSFER

    @property
    def is_refund(self):
        return self.type == self.Type.EXPENSE and self.amount < 0

    def clean(self):
        errors = {}

        if self.account_id and self.account.household_id != self.household_id:
            errors["account"] = _("Рахунок належить іншій сім'ї.")

        if self.member_id and self.member.household_id != self.household_id:
            errors["member"] = _("Ця людина не є учасником сім'ї.")

        if self.is_transfer:
            if not self.to_account_id:
                errors["to_account"] = _("Вкажіть, на який рахунок переказ.")
            elif self.to_account_id == self.account_id:
                errors["to_account"] = _("Оберіть інший рахунок.")
            elif self.to_account.household_id != self.household_id:
                errors["to_account"] = _("Рахунок належить іншій сім'ї.")
            if self.category_id:
                errors["category"] = _("У переказу немає категорії.")
        else:
            if self.to_account_id:
                errors["to_account"] = _("Рахунок зарахування потрібен лише для переказу.")
            if not self.category_id:
                errors["category"] = _("Оберіть категорію.")
            elif self.category.household_id != self.household_id:
                errors["category"] = _("Категорія належить іншій сім'ї.")
            elif self.category.kind != self.type:
                errors["category"] = _("Категорія не підходить до типу операції.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        currency_changed = self.currency != self.account.currency
        self.currency = self.account.currency
        if self.rate is None or currency_changed:
            self.rate = convert_rate(self.currency, self.household.base_currency, self.date)
        self.amount_base = (self.amount * self.rate).quantize(CENT, rounding=ROUND_HALF_UP)

        if self.is_transfer and self.to_amount is None:
            if self.to_account.currency == self.currency:
                self.to_amount = self.amount
            else:
                to_rate = convert_rate(self.to_account.currency, self.household.base_currency, self.date)
                self.to_amount = (self.amount_base / to_rate).quantize(CENT, rounding=ROUND_HALF_UP)

        super().save(*args, **kwargs)

class MerchantRule(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="merchant_rules", verbose_name=_("сім'я")
    )
    key = models.CharField(_("магазин"), max_length=80)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="+", verbose_name=_("категорія"))
    updated_at = models.DateTimeField(_("оновлено"), auto_now=True)

    class Meta:
        verbose_name = _("правило категорії")
        verbose_name_plural = _("правила категорій")
        constraints = [
            models.UniqueConstraint(fields=["household", "key"], name="unique_merchant_rule"),
        ]

    def __str__(self):
        return f"{self.key} → {self.category}"
