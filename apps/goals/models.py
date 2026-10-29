from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.households.models import Currency, Household, Membership
from apps.money.models import CENT, MONEY, Account
from apps.money.rates import RateNotFound, convert_amount


class GoalQuerySet(models.QuerySet):
    def with_saved(self):
        return self.annotate(saved=Coalesce(Sum("contributions__amount"), Decimal("0")))


class Goal(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="goals", verbose_name=_("сім'я")
    )
    name = models.CharField(_("назва"), max_length=80)
    icon = models.CharField(_("іконка"), max_length=40, blank=True, default="target")
    emoji = models.CharField(_("емодзі"), max_length=16, blank=True)
    color_slot = models.PositiveSmallIntegerField(_("колір"), default=1)
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="goals",
        verbose_name=_("рахунок"),
        help_text=_("Порожньо — внески записуються вручну"),
    )
    target_amount = models.DecimalField(_("ціль"), **MONEY)
    currency_code = models.CharField(_("валюта"), max_length=3, choices=Currency.choices, blank=True)
    monthly_amount = models.DecimalField(_("відкладати на місяць"), null=True, blank=True, **MONEY)
    deadline = models.DateField(_("до коли"), null=True, blank=True)
    is_archived = models.BooleanField(_("в архіві"), default=False)
    created_at = models.DateTimeField(_("створено"), auto_now_add=True)

    objects = GoalQuerySet.as_manager()

    class Meta:
        verbose_name = _("ціль")
        verbose_name_plural = _("цілі")
        ordering = ["is_archived", "deadline", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(target_amount__gt=0), name="goal_target_positive"),
        ]

    def __str__(self):
        return self.name

    @property
    def letter(self):
        return self.name[:1].upper()

    @property
    def tracks_account(self):
        return self.account_id is not None

    @property
    def currency(self):
        if self.account_id:
            return self.account.currency
        return self.currency_code or self.household.base_currency

    def get_saved(self):
        contributions = self.contributions.all()
        for contribution in contributions:
            contribution.goal = self
        return sum((contribution.in_goal_currency() for contribution in contributions), Decimal("0"))

    @staticmethod
    def months_between(start, end):
        return max(1, (end.year - start.year) * 12 + end.month - start.month)

    def monthly_needed(self, saved, today=None):
        left = self.target_amount - saved
        if left <= 0 or not self.deadline:
            return Decimal("0")
        today = today or timezone.localdate()
        months = self.months_between(today, self.deadline)
        return (left / months).quantize(CENT, rounding=ROUND_HALF_UP)

    def monthly_plan(self, saved, today=None):
        if saved >= self.target_amount:
            return Decimal("0")
        if self.deadline:
            return self.monthly_needed(saved, today)
        return self.monthly_amount or Decimal("0")

    def progress(self, saved):
        return max(0, min(100, int(saved * 100 / self.target_amount)))


class GoalContribution(models.Model):
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="contributions", verbose_name=_("ціль"))
    date = models.DateField(_("дата"), default=timezone.localdate)
    amount = models.DecimalField(_("сума"), **MONEY)
    member = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="goal_contributions",
        verbose_name=_("хто"),
    )
    note = models.CharField(_("нотатка"), max_length=200, blank=True)
    currency = models.CharField(
        _("валюта"), max_length=3, choices=Currency.choices, blank=True, help_text=_("Порожньо — основна валюта сім'ї")
    )
    transaction = models.OneToOneField(
        "money.Transaction",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="goal_contribution",
        verbose_name=_("переказ"),
    )

    class Meta:
        verbose_name = _("внесок")
        verbose_name_plural = _("внески")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.goal}: {self.amount}"

    @property
    def in_currency(self):
        return self.currency or self.goal.household.base_currency

    def in_goal_currency(self):
        try:
            return convert_amount(self.amount, self.in_currency, self.goal.currency, self.date)
        except RateNotFound:
            return self.amount