import datetime
import json
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.budgets.income import MonthIncome
from apps.budgets.models import Limit
from apps.budgets.periods import Period
from apps.budgets.summary import BudgetMonth
from apps.core.dashboard import Overview
from apps.money.models import Transaction
from apps.recurring.models import RecurringPayment

TODAY = datetime.date(2026, 10, 25)


def add(home, account, category, amount, date, type="expense", member=None, title="x"):
    return Transaction.objects.create(
        household=home, type=type, account=account, category=category, amount=Decimal(amount),
        date=date, title=title, member=member,
    )


@pytest.fixture
def twentieth(home):
    home.month_start_day = 20
    home.save()
    return home


def test_period_from_twentieth():
    period = Period.containing(datetime.date(2026, 10, 25), 20)
    assert (period.start, period.end, period.days) == (datetime.date(2026, 10, 20), datetime.date(2026, 11, 19), 31)
    assert Period.containing(datetime.date(2026, 10, 5), 20).start == datetime.date(2026, 9, 20)
    assert period.label == "20 жовтня – 19 листопада"
    assert period.next().start == datetime.date(2026, 11, 20)


def test_calendar_period_keeps_old_behaviour():
    period = Period.containing(datetime.date(2026, 2, 10))
    assert (period.start, period.end, period.label) == (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28), "Лютий 2026")
    assert period.income_range() == (period.start, period.end)


def test_period_crossing_new_year_shows_year():
    period = Period.containing(datetime.date(2026, 12, 25), 20)
    assert period.label == "20 грудня 2026 – 19 січня"


def test_salary_two_days_early_counts_in_new_month(twentieth, mono, salary, yura):
    add(twentieth, mono, salary, "25000", datetime.date(2026, 10, 18), type="income", member=yura)

    october = MonthIncome(twentieth, Period.containing(TODAY, 20), TODAY)
    september = MonthIncome(twentieth, Period.containing(datetime.date(2026, 10, 1), 20), TODAY)

    assert october.of(yura.pk).received == Decimal("25000")
    assert september.of(yura.pk).received == 0


def test_expected_income_from_recurring_payment(twentieth, mono, salary, yura):
    add(twentieth, mono, salary, "25000", datetime.date(2026, 10, 20), type="income", member=yura)
    RecurringPayment.objects.create(
        household=twentieth, title="Аванс", type="income", amount=Decimal("15000"), account=mono,
        category=salary, member=yura, start_date=datetime.date(2026, 11, 5),
    )

    income = MonthIncome(twentieth, Period.containing(TODAY, 20), TODAY)
    person = income.of(yura.pk)

    assert (person.received, person.expected, person.total) == (Decimal("25000"), Decimal("15000"), Decimal("40000"))
    assert [part.received for part in person.parts] == [True, False]
    assert income.family.total == Decimal("40000")


def test_only_chosen_income_categories_count(twentieth, mono, salary, yura):
    gifts = twentieth.categories.get(kind="income", name="Подарунки")
    add(twentieth, mono, salary, "20000", datetime.date(2026, 10, 21), type="income", member=yura)
    add(twentieth, mono, gifts, "5000", datetime.date(2026, 10, 22), type="income", member=yura)
    period = Period.containing(TODAY, 20)

    assert MonthIncome(twentieth, period, TODAY).of(yura.pk).received == Decimal("20000")

    yura.income_categories.set([salary, gifts])
    assert MonthIncome(twentieth, period, TODAY).of(yura.pk).received == Decimal("25000")


def test_percent_limit_grows_with_income(twentieth, mono, food, salary, yura):
    add(twentieth, mono, salary, "40000", datetime.date(2026, 10, 20), type="income", member=yura)
    RecurringPayment.objects.create(
        household=twentieth, title="Друга частина", type="income", amount=Decimal("25000"), account=mono,
        category=salary, member=yura, start_date=datetime.date(2026, 11, 5),
    )
    Limit.objects.create(household=twentieth, category=food, percent=Decimal("15"))
    add(twentieth, mono, food, "5100", datetime.date(2026, 10, 24))

    budget = BudgetMonth(twentieth, Period.containing(TODAY, 20), TODAY)
    item = budget.limits()[0]

    assert (item["amount"], item["full"], item["grows"]) == (Decimal("6000"), Decimal("9750"), Decimal("3750"))
    assert item["state"] == Limit.State.WARN
    assert budget.next_income_date() == datetime.date(2026, 11, 5)


def test_personal_percent_limit_uses_own_income(twentieth, mono, food, salary, yura, olya):
    add(twentieth, mono, salary, "30000", datetime.date(2026, 10, 20), type="income", member=yura)
    add(twentieth, mono, salary, "10000", datetime.date(2026, 10, 20), type="income", member=olya)
    Limit.objects.create(household=twentieth, category=food, member=olya, percent=Decimal("10"))

    item = BudgetMonth(twentieth, Period.containing(TODAY, 20), TODAY).limits()[0]

    assert item["amount"] == Decimal("1000")


def test_percent_limit_without_income_is_empty(twentieth, food):
    Limit.objects.create(household=twentieth, category=food, percent=Decimal("10"))

    item = BudgetMonth(twentieth, Period.containing(TODAY, 20), TODAY).limits()[0]

    assert (item["amount"], item["state"]) == (0, Limit.State.OK)


def test_overview_counts_from_month_start(twentieth, mono, food):
    add(twentieth, mono, food, "700", datetime.date(2026, 10, 19))
    add(twentieth, mono, food, "300", datetime.date(2026, 10, 21))

    overview = Overview(twentieth, today=TODAY)

    assert overview.spent == Decimal("300")
    assert (overview.day, overview.days_in_month) == (6, 31)


def test_create_percent_limit(client, twentieth, yura, food):
    client.force_login(yura.user)

    response = client.post(reverse("budgets:limit_create"), {"category": food.pk, "kind": "percent", "percent": "12,5", "member": ""})

    assert json.loads(response["HX-Trigger"])["limitsChanged"]
    limit = Limit.objects.get()
    assert (limit.percent, limit.amount) == (Decimal("12.50"), None)


def test_percent_limit_needs_value(client, twentieth, yura, food):
    client.force_login(yura.user)

    response = client.post(reverse("budgets:limit_create"), {"category": food.pk, "kind": "percent", "percent": "", "amount": "500"})

    assert "Вкажіть відсоток" in response.content.decode()
    assert not Limit.objects.exists()


def test_percent_preview(client, home, yura, mono, salary):
    add(home, mono, salary, "30000", datetime.date.today(), type="income", member=yura)
    client.force_login(yura.user)

    response = client.get(reverse("budgets:limit_preview"), {"percent": "10"})

    assert "3 000" in response.content.decode().replace(" ", " ")


def test_budget_page_shows_period_and_income(client, twentieth, yura, mono, salary):
    client.force_login(yura.user)
    add(twentieth, mono, salary, "30000", datetime.date.today(), type="income", member=yura)

    page = client.get(reverse("budgets:budget")).content.decode()

    assert "Дохід бюджетного місяця" in page
    assert twentieth.period().label in page


def test_only_owner_changes_month_start(client, home, yura, olya):
    client.force_login(olya.user)
    assert client.post(reverse("households:month_start"), {"day": "20"}).status_code == 403

    client.force_login(yura.user)
    client.post(reverse("households:month_start"), {"day": "other", "other_day": "22"})
    home.refresh_from_db()
    assert home.month_start_day == 22


def test_member_sets_own_income_categories(client, home, olya, salary):
    gifts = home.categories.get(kind="income", name="Подарунки")
    client.force_login(olya.user)

    client.post(reverse("households:income_categories"), {"category": [salary.pk, gifts.pk]})

    assert set(olya.income_categories.all()) == {salary, gifts}


def test_personal_limit_inside_shared_is_not_planned_twice(home, mono, food, olya):
    Limit.objects.create(household=home, category=food, amount=Decimal("10000"))
    Limit.objects.create(household=home, category=food, member=olya, amount=Decimal("3000"))
    add(home, mono, food, "1000", datetime.date(2026, 10, 10), member=olya)

    budget = BudgetMonth(home, Period.containing(datetime.date(2026, 10, 20)), datetime.date(2026, 10, 20))
    summary = budget.summary(budget.limits())

    assert (summary["planned"], summary["spent"]) == (Decimal("10000"), Decimal("1000"))
