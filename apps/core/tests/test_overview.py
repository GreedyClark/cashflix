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


def test_left_for_month_subtracts_savings(home, mono, food, salary):
    import datetime
    from decimal import Decimal

    from apps.core.dashboard import Overview
    from apps.money.models import Account, Transaction

    jar = Account.objects.create(household=home, name="Банка", kind=Account.Kind.SAVINGS)
    today = datetime.date(2026, 10, 20)
    Transaction.objects.create(household=home, account=mono, category=salary, type="income", amount=Decimal("30000"), date=datetime.date(2026, 10, 2), title="ЗП")
    Transaction.objects.create(household=home, account=mono, category=food, amount=Decimal("8000"), date=datetime.date(2026, 10, 5), title="x")
    Transaction.objects.create(household=home, account=mono, to_account=jar, type="transfer", amount=Decimal("5000"), date=datetime.date(2026, 10, 6), title="У банку")

    kpis = Overview(home, today=today).kpis()

    assert (kpis["left"], kpis["saved"]) == (Decimal("17000"), Decimal("5000"))
    assert kpis["live"] == Decimal("18000") and kpis["capital"] == Decimal("23000")


def test_forecast_adds_unpaid_recurring(home, mono, food):
    import datetime
    from decimal import Decimal

    from apps.core.dashboard import Overview
    from apps.money.models import Transaction
    from apps.recurring.models import RecurringPayment

    today = datetime.date(2026, 10, 10)
    Transaction.objects.create(household=home, account=mono, category=food, amount=Decimal("1000"), date=datetime.date(2026, 10, 5), title="x")
    RecurringPayment.objects.create(household=home, title="Квартира", amount=Decimal("12000"), account=mono, category=food, start_date=datetime.date(2026, 10, 28))

    overview = Overview(home, today=today)

    assert overview.forecast_total == Decimal("1000") + Decimal("100") * 21 + Decimal("12000")
