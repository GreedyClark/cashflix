from datetime import timedelta
from decimal import Decimal
from functools import cached_property

from django.db.models import Q, Sum
from django.utils import formats, timezone

from apps.budgets.income import MonthIncome
from apps.budgets.models import Limit
from apps.budgets.summary import limit_item
from apps.goals.services import goal_items
from apps.money.accounts import load_accounts

ZERO = Decimal("0")


def percent_change(now, before):
    if not before:
        return None
    return round((now - before) / before * 100)


def by_day(queryset):
    rows = queryset.order_by().values("date").annotate(total=Sum("amount_base")).values_list("date", "total")
    return dict(rows)


def running_total(amounts, start, days):
    total = ZERO
    result = []
    for offset in range(days):
        total += amounts.get(start + timedelta(days=offset), ZERO)
        result.append(total)
    return result


def as_floats(values):
    return [None if value is None else float(value) for value in values]


def incomes_of(transactions, period, until):
    start, end = period.income_range()
    return transactions.incomes().between(start, min(end, until))


class Overview:
    def __init__(self, household, member=None, today=None):
        self.household = household
        self.member = member
        self.today = today or timezone.localdate()
        self.period = household.period(self.today)
        self.month = self.period.start
        self.days_in_month = self.period.days
        self.previous = self.period.previous()

        transactions = household.transactions.all()
        if member:
            transactions = transactions.filter(member=member)
        self.transactions = transactions

        self.this_month = transactions.between(self.month, self.today)
        self.spent = self.this_month.expenses().total_base()
        self.earned = incomes_of(transactions, self.period, self.today).total_base()
        self.spent_by_day = by_day(self.this_month.expenses())

    @property
    def day(self):
        return self.period.day_number(self.today)

    def same_days_of(self, period):
        return min(period.start + timedelta(days=self.day - 1), period.end)

    def same_period_last_month(self):
        return self.transactions.between(self.previous.start, self.same_days_of(self.previous))

    def earned_last_month(self):
        start = self.period.income_range()[0]
        previous_start, previous_end = self.previous.income_range()
        until = min(previous_start + (self.today - start), previous_end)
        return self.transactions.incomes().between(previous_start, until).total_base()

    def kpis(self):
        before = self.same_period_last_month()
        forecast = self.spent / self.day * self.days_in_month
        savings = round((self.earned - forecast) / self.earned * 100) if self.earned else None
        return {
            "balance": self.total_balance,
            "earned": self.earned,
            "earned_change": percent_change(self.earned, self.earned_last_month()),
            "spent": self.spent,
            "spent_change": percent_change(self.spent, before.expenses().total_base()),
            "savings": savings,
        }

    @cached_property
    def accounts(self):
        return load_accounts(self.household, self.today)

    @cached_property
    def total_balance(self):
        return sum((a.converted for a in self.accounts if a.converted is not None), ZERO)

    def spending(self):
        current = running_total(self.spent_by_day, self.month, self.day)
        previous_days = self.previous.days
        previous_by_day = by_day(self.transactions.between(self.previous.start, self.previous.end).expenses())
        previous = running_total(previous_by_day, self.previous.start, previous_days)
        previous = (previous + previous[-1:] * self.days_in_month)[: self.days_in_month]

        per_day = self.spent / self.day
        forecast = [None] * (self.day - 1) + [self.spent]
        forecast += [per_day * number for number in range(self.day + 1, self.days_in_month + 1)]

        biggest = max(self.spent_by_day.items(), key=lambda item: item[1], default=None)
        days_left = self.days_in_month - self.day + 1
        room = self.earned - self.spent
        return {
            "total": self.spent,
            "change": percent_change(self.spent, self.same_period_last_month().expenses().total_base()),
            "forecast": per_day * self.days_in_month,
            "per_day": per_day,
            "biggest_day": biggest,
            "room": room,
            "room_per_day": room / days_left if room > 0 else None,
            "chart": {
                "days": self.days_in_month,
                "today": self.day,
                "current": as_floats(current + [None] * (self.days_in_month - self.day)),
                "forecast": as_floats(forecast),
                "previous": as_floats(previous),
                "income": float(self.earned),
                "ticks": [day.day for day in self.period.dates()],
                "titles": [formats.date_format(day, "j E") for day in self.period.dates()],
            },
        }

    def half_year(self):
        periods = [self.period.shift(offset) for offset in range(-5, 1)]
        earned, spent = [], []
        for period in periods:
            until = min(period.end, self.today)
            earned.append(incomes_of(self.transactions, period, until).total_base())
            spent.append(self.transactions.between(period.start, until).expenses().total_base())
        saved = [e - s for e, s in zip(earned, spent)]
        finished = saved[:-1]
        best = max(range(len(finished)), key=lambda i: finished[i]) if finished else None
        return {
            "average_saved": sum(finished, ZERO) / len(finished) if finished else ZERO,
            "best_month": periods[best] if best is not None else None,
            "best_saved": finished[best] if best is not None else ZERO,
            "total_saved": sum(saved, ZERO),
            "chart": {
                "labels": [period.chart_label for period in periods],
                "earned": as_floats(earned),
                "spent": as_floats(spent),
                "savings": [round(float(s / e * 100)) if e else 0 for s, e in zip(saved, earned)],
            },
        }

    def categories(self):
        before = by_category(self.same_period_last_month().expenses())
        now = by_category(self.this_month.expenses())
        lookup = self.household.categories.in_bulk(list(now))
        items = []
        for pk, amount in sorted(now.items(), key=lambda item: item[1], reverse=True):
            category = lookup[pk]
            items.append({
                "category": category,
                "amount": amount,
                "share": round(amount / self.spent * 100) if self.spent else 0,
                "change": percent_change(amount, before.get(pk)),
            })
        return items

    def limits(self):
        limits = Limit.objects.filter(household=self.household).select_related("category", "member__user")
        if self.member:
            limits = limits.filter(Q(member__isnull=True) | Q(member=self.member))
        income = MonthIncome(self.household, self.period, self.today)
        return [limit_item(limit, limit.spent, income) for limit in limits.with_spent(self.period.start, self.period.end)]

    def pace(self):
        return round(self.day / self.days_in_month * 100)

    def upcoming(self, days=7):
        end = self.today + timedelta(days=days)
        payments = self.household.recurring_payments.filter(is_active=True, next_date__lte=end)
        if self.member:
            payments = payments.filter(Q(member=self.member) | Q(member__isnull=True))
        payments = payments.select_related("account", "category").order_by("next_date")
        for payment in payments:
            payment.days_left = (payment.next_date - self.today).days
        return payments

    def recent(self, count=8):
        items = self.transactions.select_related("category", "account", "to_account", "member__user")[:count]
        days = []
        for tx in items:
            if not days or days[-1]["date"] != tx.date:
                days.append({"date": tx.date, "items": []})
            days[-1]["items"].append(tx)
        return days

    def goals(self):
        return goal_items(self.household, self.today)

    def chart_data(self, spending, half_year, categories):
        return {
            "spending": spending["chart"],
            "halfYear": half_year["chart"],
            "categories": {
                "labels": [item["category"].name for item in categories],
                "values": [float(item["amount"]) for item in categories],
                "slots": [item["category"].color_slot for item in categories],
            },
            "balance": as_floats(self.balance_by_day()),
        }

    def balance_by_day(self):
        incomes = by_day(self.this_month.incomes())
        net = {date: incomes.get(date, ZERO) - self.spent_by_day.get(date, ZERO) for date in {*incomes, *self.spent_by_day}}
        changes = running_total(net, self.month, self.day)
        start = self.total_balance - (changes[-1] if changes else ZERO)
        return [start + change for change in changes]


def by_category(queryset):
    rows = queryset.order_by().values("category").annotate(total=Sum("amount_base")).values_list("category", "total")
    return dict(rows)
