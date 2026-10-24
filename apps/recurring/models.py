import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.households.models import Currency, Household, Membership
from apps.money.models import MONEY, Account, Category, Transaction
from apps.money.rates import convert_rate

from .dates import add_months


def default_reminders():
    return [1, 0]


class RecurringPayment(models.Model):
    REMIND_CHOICES = [(7, _("За 7 днів")), (3, _("За 3 дні")), (1, _("За день")), (0, _("У день оплати"))]

    class Period(models.TextChoices):
        WEEKLY = "weekly", _("щотижня")
        MONTHLY = "monthly", _("щомісяця")
        YEARLY = "yearly", _("щороку")

    class Mode(models.TextChoices):
        AUTO = "auto", _("Автоматично")
        REMIND = "remind", _("Нагадати, оплачу сам")

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="recurring_payments", verbose_name=_("сім'я")
    )
    title = models.CharField(_("назва"), max_length=120)
    type = models.CharField(
        _("тип"),
        max_length=10,
        choices=[(Transaction.Type.EXPENSE, _("витрата")), (Transaction.Type.INCOME, _("дохід"))],
        default=Transaction.Type.EXPENSE,
    )
    amount = models.DecimalField(_("сума"), **MONEY)
    currency = models.CharField(_("валюта"), max_length=3, choices=Currency.choices, blank=True)
    is_approximate = models.BooleanField(_("сума орієнтовна"), default=False)
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="recurring_payments", verbose_name=_("рахунок")
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="recurring_payments", verbose_name=_("категорія")
    )
    member = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recurring_payments",
        verbose_name=_("хто"),
    )
    period = models.CharField(_("періодичність"), max_length=10, choices=Period.choices, default=Period.MONTHLY)
    start_date = models.DateField(_("перший платіж"), default=timezone.localdate)
    next_date = models.DateField(_("наступний платіж"), blank=True)
    is_active = models.BooleanField(_("активний"), default=True)
    mode = models.CharField(_("як записувати"), max_length=10, choices=Mode.choices, default=Mode.AUTO)
    reminders = models.JSONField(_("нагадати"), default=default_reminders, blank=True)
    remind_on = models.DateField(_("нагадати ще раз"), null=True, blank=True)
    created_at = models.DateTimeField(_("створено"), auto_now_add=True)

    class Meta:
        verbose_name = _("регулярний платіж")
        verbose_name_plural = _("регулярні платежі")
        ordering = ["-is_active", "next_date"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="recurring_amount_positive"),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_period_display()})"

    def clean(self):
        errors = {}
        if self.account_id and self.account.household_id != self.household_id:
            errors["account"] = _("Рахунок належить іншій сім'ї.")
        if self.category_id:
            if self.category.household_id != self.household_id:
                errors["category"] = _("Категорія належить іншій сім'ї.")
            elif self.category.kind != self.type:
                errors["category"] = _("Категорія не підходить до типу платежу.")
        if self.member_id and self.member.household_id != self.household_id:
            errors["member"] = _("Ця людина не є учасником сім'ї.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.next_date:
            self.next_date = self.start_date
        super().save(*args, **kwargs)

    def following_date(self, date):
        if self.period == self.Period.WEEKLY:
            return date + datetime.timedelta(weeks=1)
        if self.period == self.Period.YEARLY:
            return add_months(date, 12, day=self.start_date.day)
        return add_months(date, 1, day=self.start_date.day)

    @property
    def pay_currency(self):
        return self.currency or self.account.currency

    @property
    def is_foreign(self):
        return self.pay_currency != self.account.currency

    @property
    def is_manual(self):
        return self.mode == self.Mode.REMIND

    def account_amount(self, date, amount=None):
        amount = self.amount if amount is None else amount
        if not self.is_foreign:
            return amount
        rate = convert_rate(self.pay_currency, self.account.currency, date)
        return (amount * rate).quantize(Decimal("0.01"))

    def make_transaction(self, date, account_amount=None):
        return Transaction(
            household=self.household,
            type=self.type,
            date=date,
            title=self.title,
            account=self.account,
            amount=self.account_amount(date) if account_amount is None else account_amount,
            category=self.category,
            member=self.member,
            source=Transaction.Source.RECURRING,
        )