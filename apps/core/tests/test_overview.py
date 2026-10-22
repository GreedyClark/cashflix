import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.dashboard import Overview
from apps.money.models import Transaction

TODAY = datetime.date(2026, 10, 10)


def add(home, account, amount, date, **fields):
    fields.setdefault("title", "Покупка")
    return Transaction.objects.create(household=home, account=account, amount=Decimal(amount), date=date, **fields)


@pytest.fixture
def october(home, mono, food, salary, yura, olya):
    add(home, mono, "1000", datetime.date(2026, 10, 2), category=food, member=yura)
    add(home, mono, "500", datetime.date(2026, 10, 5), category=food, member=olya)
    add(home, mono, "20000", datetime.date(2026, 10, 1), type="income", category=salary, member=yura)
    add(home, mono, "1200", datetime.date(2026, 9, 3), category=food, member=yura)


def test_kpis_and_spending(home, october):
    overview = Overview(home, today=TODAY)
    kpis = overview.kpis()
    spending = overview.spending()

    assert kpis["spent"] == Decimal("1500")
    assert kpis["earned"] == Decimal("20000")
    assert kpis["spent_change"] == 25
    assert spending["per_day"] == Decimal("150")
    assert spending["biggest_day"] == (datetime.date(2026, 10, 2), Decimal("1000"))
    assert spending["chart"]["current"][9] == 1500.0
    assert spending["chart"]["forecast"][-1] == 4650.0


def test_member_view_counts_only_their_operations(home, october, olya):
    overview = Overview(home, member=olya, today=TODAY)

    assert overview.kpis()["spent"] == Decimal("500")
    assert [item["amount"] for item in overview.categories()] == [Decimal("500")]


def test_balance_includes_opening_balance(home, mono, october):
    assert Overview(home, today=TODAY).total_balance == Decimal("1000") + Decimal("20000") - Decimal("2700")


def test_page_renders_for_empty_family(auth_client):
    response = auth_client.get(reverse("core:home"))

    assert response.status_code == 200
    assert "overview-data" in response.content.decode()


def test_other_family_member_param_is_ignored(client, yura, olya, user_household):
    stranger = user_household.memberships.get()
    client.force_login(yura.user)

    response = client.get(reverse("core:home"), {"member": stranger.pk})

    assert response.context["member"] is None
