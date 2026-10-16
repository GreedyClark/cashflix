from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.households.models import Household, Membership
from apps.money.models import CENT, MONEY


class GoalQuerySet(models.QuerySet):
    def with_saved(self):
        return self.annotate(saved=Coalesce(Sum("contributions__amount"), Decimal("0")))


class Goal(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="goals", verbose_name=_("господарство")
    )
    name = models.CharField(_("назва"), max_length=80)
    icon = models.CharField(_("іконка"), max_length=40, default="target")
    target_amount = models.DecimalField(_("ціль"), **MONEY)
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

    def get_saved(self):
        return self.contributions.aggregate(total=Coalesce(Sum("amount"), Decimal("0")))["total"]

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

    def progress(self, saved):
        return min(100, int(saved * 100 / self.target_amount))


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

    class Meta:
        verbose_name = _("внесок")
        verbose_name_plural = _("внески")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.goal}: {self.amount}"