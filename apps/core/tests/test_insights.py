import datetime
from decimal import Decimal

from apps.budgets.models import Limit
from apps.core.dashboard import Overview
from apps.core.insights import Insights
from apps.money.models import Transaction

TODAY = datetime.date(2026, 10, 20)


def add(home, account, category, amount, date, type="expense", title="x"):
    Transaction.objects.create(
        household=home, type=type, account=account, category=category, amount=Decimal(amount), date=date, title=title,
    )


def insights(home):
    return Insights(Overview(home, today=TODAY))


def test_category_spike_against_same_days_of_previous_months(home, mono, food):
    for month in (7, 8, 9):
        add(home, mono, food, "1000", datetime.date(2026, month, 10))
        add(home, mono, food, "5000", datetime.date(2026, month, 28))
    add(home, mono, food, "2500", datetime.date(2026, 10, 10))

    found = insights(home).categories()

    assert len(found) == 1
    assert found[0].tone == "warn"
    assert "150%" in found[0].text


def test_small_differences_are_ignored(home, mono, food):
    for month in (7, 8, 9):
        add(home, mono, food, "200", datetime.date(2026, month, 10))
    add(home, mono, food, "600", datetime.date(2026, 10, 10))

    assert insights(home).categories() == []


def test_forecast_plus_and_minus(home, mono, food, salary):
    add(home, mono, salary, "30000", datetime.date(2026, 10, 1), type="income")
    add(home, mono, food, "10000", datetime.date(2026, 10, 5))
    assert insights(home).forecast()[0].tone == "good"

    add(home, mono, food, "20000", datetime.date(2026, 10, 6))
    assert insights(home).forecast()[0].tone == "warn"


def test_limit_runs_out_before_month_end(home, mono, food):
    Limit.objects.create(household=home, category=food, amount=Decimal("3000"))
    add(home, mono, food, "2400", datetime.date(2026, 10, 10))

    found = insights(home).limits()

    assert len(found) == 1
    assert "25 жовтня" in found[0].text


def test_biggest_expense_names_category(home, mono, food, home_subs):
    add(home, mono, food, "100", datetime.date(2026, 10, 3))
    add(home, mono, food, "200", datetime.date(2026, 10, 3))
    add(home, mono, home_subs, "9000", datetime.date(2026, 10, 4), title="Magazin")

    found = insights(home).biggest()

    assert "«Підписки»" in found[0].text and "Magazin" not in found[0].text


def test_biggest_expense_needs_a_few_expenses(home, mono, food):
    add(home, mono, food, "200", datetime.date(2026, 10, 3), title="Magazin")

    assert insights(home).biggest() == []


def test_overview_shows_at_most_four(client, yura, home, mono, food, salary):
    client.force_login(yura.user)
    add(home, mono, salary, "1000", datetime.date.today().replace(day=1), type="income")

    response = client.get("/")

    assert len(response.context["insights"]) <= 4
