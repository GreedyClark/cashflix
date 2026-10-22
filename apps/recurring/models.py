import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.households.models import Household, Membership
from apps.money.models import MONEY, Account, Category, Transaction

from .dates import add_months


class RecurringPayment(models.Model):
    class Period(models.TextChoices):
        WEEKLY = "weekly", _("щотижня")
        MONTHLY = "monthly", _("щомісяця")
        YEARLY = "yearly", _("щороку")

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

    def make_transaction(self, date):
        return Transaction(
            household=self.household,
            type=self.type,
            date=date,
            title=self.title,
            account=self.account,
            amount=self.amount,
            category=self.category,
            member=self.member,
            source=Transaction.Source.RECURRING,
        )