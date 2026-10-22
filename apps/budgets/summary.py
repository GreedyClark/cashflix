import calendar
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from apps.money.models import Category, Transaction
from apps.recurring.dates import add_months

from .models import Limit

ZERO = Decimal("0")
AVERAGE_MONTHS = 3


def month_end(month):
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def spending_by_member(household, start, end):
    rows = (
        Transaction.objects.filter(household=household)
        .expenses()
        .between(start, end)
        .order_by()
        .values("category", "member")
        .annotate(total=Sum("amount_base"))
    )
    result = defaultdict(lambda: ZERO)
    for row in rows:
        if row["member"]:
            result[(row["category"], row["member"])] += row["total"]
        result[(row["category"], None)] += row["total"]
    return result


def round_hint(value):
    if value >= 1000:
        return (value / 50).quantize(Decimal("1")) * 50
    return (value / 10).quantize(Decimal("1")) * 10


@dataclass
class History:
    average: Decimal
    previous: Decimal


class SpendingHistory:
    def __init__(self, household, month):
        first = add_months(month, -AVERAGE_MONTHS)
        last_month = add_months(month, -1)
        self.totals = spending_by_member(household, first, month_end(last_month))
        self.previous = spending_by_member(household, last_month, month_end(last_month))

    def for_limit(self, category_id, member_id=None):
        key = (category_id, member_id)
        return History(
            average=round_hint(self.totals[key] / AVERAGE_MONTHS),
            previous=round_hint(self.previous[key]),
        )


class BudgetMonth:
    def __init__(self, household, month, today):
        self.household = household
        self.month = month
        self.end = month_end(month)
        self.today = today
        self.history = SpendingHistory(household, month)

    @property
    def is_current(self):
        return self.month <= self.today <= self.end

    @property
    def pace(self):
        if self.today > self.end:
            return 100
        if self.today < self.month:
            return 0
        return round(self.today.day / self.end.day * 100)

    @property
    def days_left(self):
        return (self.end - self.today).days + 1 if self.is_current else 0

    def limits(self):
        limits = (
            Limit.objects.filter(household=self.household, category__is_archived=False)
            .select_related("category", "member__user")
            .with_spent(self.month, self.end)
            .order_by("category__order", "category__name", "member")
        )
        items = []
        for limit in limits:
            history = self.history.for_limit(limit.category_id, limit.member_id)
            items.append({
                "limit": limit,
                "spent": limit.spent,
                "left": limit.amount - limit.spent,
                "over": limit.spent - limit.amount,
                "percent": round(limit.spent / limit.amount * 100),
                "bar": min(100, round(limit.spent / limit.amount * 100)),
                "state": limit.state_for(limit.spent),
                "average": history.average,
                "pace": self.pace if self.is_current else None,
            })
        return items

    def free_categories(self, limits):
        taken = {item["limit"].category_id for item in limits}
        categories = self.household.categories.filter(kind=Category.Kind.EXPENSE, is_archived=False).exclude(pk__in=taken)
        spent = spending_by_member(self.household, self.month, self.end)
        return [
            {"category": c, "spent": spent[(c.pk, None)], "average": self.history.for_limit(c.pk).average}
            for c in categories
        ]

    def summary(self, limits):
        planned = sum((item["limit"].amount for item in limits), ZERO)
        spent = sum((item["spent"] for item in limits), ZERO)
        left = planned - spent
        days_left = self.days_left
        return {
            "planned": planned,
            "spent": spent,
            "left": left,
            "percent": round(spent / planned * 100) if planned else 0,
            "bar": min(100, round(spent / planned * 100)) if planned else 0,
            "per_day": left / days_left if days_left and left > 0 else None,
            "days_left": days_left,
            "pace": self.pace,
            "over": list(dict.fromkeys(i["limit"].category.name for i in limits if i["state"] == Limit.State.CRIT)),
            "close": list(dict.fromkeys(i["limit"].category.name for i in limits if i["state"] == Limit.State.WARN)),
        }
