from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Case, DecimalField, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _

from apps.households.models import Household, Membership
from apps.money.models import MONEY, Category, Transaction


class LimitQuerySet(models.QuerySet):
    def with_spent(self, start, end):
        expenses = Transaction.objects.filter(
            category=OuterRef("category"),
            type=Transaction.Type.EXPENSE,
            date__gte=start,
            date__lte=end,
        )
        personal = expenses.filter(member=OuterRef("member"))

        def total(queryset):
            subquery = queryset.order_by().values("category").annotate(s=Sum("amount_base")).values("s")
            zero = Value(Decimal("0"), output_field=DecimalField(**MONEY))
            return Coalesce(Subquery(subquery, output_field=DecimalField(**MONEY)), zero)

        return self.annotate(
            spent=Case(When(member__isnull=True, then=total(expenses)), default=total(personal)),
        )


class Limit(models.Model):
    WARN_AT = Decimal("0.8")

    class State(models.TextChoices):
        OK = "ok", _("у межах")
        WARN = "warn", _("майже вичерпано")
        CRIT = "crit", _("перевищено")

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="limits", verbose_name=_("сім'я")
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="limits", verbose_name=_("категорія")
    )
    member = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="limits",
        verbose_name=_("для кого"),
        help_text=_("Порожньо — спільний ліміт на всю сім'ю"),
    )
    amount = models.DecimalField(_("ліміт на місяць"), **MONEY)
    created_at = models.DateTimeField(_("створено"), auto_now_add=True)

    objects = LimitQuerySet.as_manager()

    class Meta:
        verbose_name = _("ліміт")
        verbose_name_plural = _("ліміти")
        ordering = ["category__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["category"], condition=Q(member__isnull=True), name="unique_shared_limit"
            ),
            models.UniqueConstraint(
                fields=["category", "member"], condition=Q(member__isnull=False), name="unique_personal_limit"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="limit_amount_positive"),
        ]

    def __str__(self):
        who = self.member.user.name if self.member_id else _("спільний")
        return f"{self.category} ({who}): {self.amount}"

    @property
    def is_shared(self):
        return self.member_id is None

    def clean(self):
        errors = {}
        if self.category_id:
            if self.category.household_id != self.household_id:
                errors["category"] = _("Категорія належить іншій сім'ї.")
            elif self.category.kind != Category.Kind.EXPENSE:
                errors["category"] = _("Ліміт можна поставити лише на категорію витрат.")
        if self.member_id and self.member.household_id != self.household_id:
            errors["member"] = _("Ця людина не є учасником сім'ї.")
        if errors:
            raise ValidationError(errors)

    def spent_between(self, start, end):
        expenses = Transaction.objects.expenses().between(start, end).filter(category=self.category)
        if not self.is_shared:
            expenses = expenses.filter(member=self.member)
        return expenses.total_base()

    def state_for(self, spent):
        if spent >= self.amount:
            return self.State.CRIT
        if spent >= self.amount * self.WARN_AT:
            return self.State.WARN
        return self.State.OK