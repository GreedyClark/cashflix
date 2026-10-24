import calendar
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from apps.money.models import Category, Transaction

from .income import MonthIncome
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
    def __init__(self, household, period):
        last = period.previous()
        self.totals = spending_by_member(household, period.shift(-AVERAGE_MONTHS).start, last.end)
        self.previous = spending_by_member(household, last.start, last.end)

    def for_limit(self, category_id, member_id=None):
        key = (category_id, member_id)
        return History(
            average=round_hint(self.totals[key] / AVERAGE_MONTHS),
            previous=round_hint(self.previous[key]),
        )


def pace_of(period, today):
    if today > period.end:
        return 100
    if today < period.start:
        return 0
    return round(period.day_number(today) / period.days * 100)


def limit_item(limit, spent, income, pace=None, average=None):
    amount, full = income.amounts(limit)
    ratio = spent / amount * 100 if amount else (100 if spent else 0)
    item = {
        "limit": limit,
        "amount": amount,
        "full": full,
        "grows": full - amount if full > amount else ZERO,
        "spent": spent,
        "left": amount - spent,
        "over": spent - amount,
        "percent": round(ratio),
        "bar": min(100, round(ratio)),
        "state": limit.state_for(spent, amount),
        "average": average,
        "pace": pace,
        "available": None,
    }
    if limit.is_percent and full > amount:
        item["available"] = min(100, round(amount / full * 100))
        item["bar"] = min(100, round(spent / full * 100))
        item["pace"] = None
    return item


class BudgetMonth:
    def __init__(self, household, period, today):
        self.household = household
        self.period = period
        self.today = today
        self.history = SpendingHistory(household, period)
        self.income = MonthIncome(household, period, today)

    @property
    def is_current(self):
        return self.period.contains(self.today)

    @property
    def pace(self):
        return pace_of(self.period, self.today)

    @property
    def days_left(self):
        return (self.period.end - self.today).days + 1 if self.is_current else 0

    def limits(self):
        limits = (
            Limit.objects.filter(household=self.household, category__is_archived=False)
            .select_related("category", "member__user")
            .with_spent(self.period.start, self.period.end)
            .order_by("category__order", "category__name", "member")
        )
        items = []
        for limit in limits:
            history = self.history.for_limit(limit.category_id, limit.member_id)
            pace = self.pace if self.is_current else None
            items.append(limit_item(limit, limit.spent, self.income, pace, history.average))
        return items

    def free_categories(self, limits):
        taken = {item["limit"].category_id for item in limits}
        categories = self.household.categories.filter(kind=Category.Kind.EXPENSE, is_archived=False).exclude(pk__in=taken)
        spent = spending_by_member(self.household, self.period.start, self.period.end)
        return [
            {"category": c, "spent": spent[(c.pk, None)], "average": self.history.for_limit(c.pk).average}
            for c in categories
        ]

    def summary(self, limits):
        planned = sum((item["amount"] for item in limits), ZERO)
        full = sum((item["full"] for item in limits), ZERO)
        spent = sum((item["spent"] for item in limits), ZERO)
        left = planned - spent
        days_left = self.days_left
        return {
            "planned": planned,
            "full": full if full > planned else None,
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

    def next_income_date(self):
        upcoming = [part.date for part in self.income.family.parts if not part.received and part.date >= self.today]
        return min(upcoming, default=None)
