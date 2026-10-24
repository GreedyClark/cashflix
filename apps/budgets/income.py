from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from apps.money.models import Category, Transaction
from apps.recurring.models import RecurringPayment
from apps.recurring.services import in_base, occurrences

ZERO = Decimal("0")
DEFAULT_CATEGORY = "Зарплата"


@dataclass
class Part:
    date: date
    amount: Decimal
    received: bool


@dataclass
class Income:
    membership: object = None
    received: Decimal = ZERO
    expected: Decimal = ZERO
    parts: list = field(default_factory=list)

    @property
    def total(self):
        return self.received + self.expected

    @property
    def percent(self):
        return min(100, round(self.received / self.total * 100)) if self.total else 0

    def add(self, other):
        self.received += other.received
        self.expected += other.expected
        self.parts += other.parts


def whole(value):
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def counted_categories(household, membership):
    chosen = {c.pk for c in membership.income_categories.all()}
    if chosen:
        return chosen
    incomes = household.categories.filter(kind=Category.Kind.INCOME)
    default = {c.pk for c in incomes if c.name == DEFAULT_CATEGORY}
    return default or {c.pk for c in incomes}


class MonthIncome:
    def __init__(self, household, period, today):
        self.household = household
        self.period = period
        self.today = today
        self.start, self.end = period.income_range()
        members = household.memberships.active().select_related("user").prefetch_related("income_categories")
        self.people = {}
        everything = set()
        for membership in members:
            categories = counted_categories(household, membership)
            everything |= categories
            self.people[membership.pk] = self.collect(membership, categories)
        shared = self.collect(None, everything)
        self.family = Income()
        for person in self.people.values():
            self.family.add(person)
        self.family.add(shared)
        self.family.parts.sort(key=lambda part: (part.date, not part.received))

    def collect(self, membership, categories):
        income = Income(membership=membership)
        received = self.household.transactions.incomes().filter(
            date__gte=self.start, date__lte=self.end, category__in=categories, member=membership
        )
        for tx in received.order_by("date"):
            income.received += tx.amount_base
            income.parts.append(Part(tx.date, tx.amount_base, True))
        payments = RecurringPayment.objects.filter(
            household=self.household,
            type=Transaction.Type.INCOME,
            is_active=True,
            member=membership,
            category__in=categories,
        ).select_related("account", "household")
        for payment in payments:
            amount = in_base(payment, payment.amount, self.today)
            if amount is None:
                continue
            for day in occurrences(payment, self.start, self.end):
                income.expected += amount
                income.parts.append(Part(day, amount, False))
        income.parts.sort(key=lambda part: (part.date, not part.received))
        return income

    def of(self, member_id):
        if member_id is None:
            return self.family
        return self.people.get(member_id, Income())

    def amounts(self, limit):
        if limit.percent is None:
            return limit.amount, limit.amount
        base = self.of(limit.member_id)
        share = limit.percent / 100
        return whole(base.received * share), whole(base.total * share)

    def has_expected(self):
        return self.family.expected > 0
