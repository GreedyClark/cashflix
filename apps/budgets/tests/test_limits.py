import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.budgets.models import Limit
from apps.money.models import Transaction

START = datetime.date(2026, 10, 1)
END = datetime.date(2026, 10, 31)


def spend(home, account, category, member, amount, date=datetime.date(2026, 10, 10)):
    return Transaction.objects.create(
        household=home, account=account, category=category, member=member, amount=Decimal(amount), date=date, title="x"
    )


def test_shared_limit_counts_everyone(home, mono, food, yura, olya):
    limit = Limit.objects.create(household=home, category=food, amount=Decimal("1000"))
    spend(home, mono, food, yura, "300")
    spend(home, mono, food, olya, "200")
    spend(home, mono, food, None, "100")

    assert limit.spent_between(START, END) == Decimal("600")


def test_personal_limit_counts_only_that_member(home, mono, food, yura, olya):
    limit = Limit.objects.create(household=home, category=food, member=olya, amount=Decimal("1000"))
    spend(home, mono, food, yura, "300")
    spend(home, mono, food, olya, "200")

    assert limit.spent_between(START, END) == Decimal("200")


def test_with_spent_annotation_matches(home, mono, food, yura, olya):
    Limit.objects.create(household=home, category=food, amount=Decimal("1000"))
    Limit.objects.create(household=home, category=food, member=olya, amount=Decimal("500"))
    spend(home, mono, food, yura, "300")
    spend(home, mono, food, olya, "200")
    spend(home, mono, food, olya, "999", date=datetime.date(2026, 9, 30))

    spent = {limit.member_id: limit.spent for limit in Limit.objects.with_spent(START, END)}

    assert spent[None] == Decimal("500")
    assert spent[olya.pk] == Decimal("200")


def test_state_thresholds(home, food):
    limit = Limit(household=home, category=food, amount=Decimal("1000"))

    assert limit.state_for(Decimal("500")) == Limit.State.OK
    assert limit.state_for(Decimal("800")) == Limit.State.WARN
    assert limit.state_for(Decimal("1000")) == Limit.State.CRIT


def test_only_one_shared_limit_per_category(home, food):
    Limit.objects.create(household=home, category=food, amount=Decimal("1000"))

    with pytest.raises(IntegrityError):
        Limit.objects.create(household=home, category=food, amount=Decimal("2000"))


def test_shared_and_personal_limits_can_coexist(home, food, olya):
    Limit.objects.create(household=home, category=food, amount=Decimal("1000"))
    Limit.objects.create(household=home, category=food, member=olya, amount=Decimal("400"))

    assert home.limits.count() == 2


def test_limit_on_income_category_is_rejected(home, salary):
    limit = Limit(household=home, category=salary, amount=Decimal("1000"))

    with pytest.raises(ValidationError):
        limit.full_clean()