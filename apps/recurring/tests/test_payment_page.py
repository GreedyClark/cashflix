import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.households.services import create_household
from apps.money.models import Transaction
from apps.recurring.models import RecurringPayment
from apps.recurring.services import first_date_from, monthly_amount, occurrences

TODAY = datetime.date(2026, 10, 22)


@pytest.fixture
def yura_client(client, yura):
    client.force_login(yura.user)
    return client


def payment(home, mono, category, **fields):
    data = {"title": "Spotify", "amount": Decimal("199"), "start_date": TODAY}
    data.update(fields)
    return RecurringPayment.objects.create(household=home, account=mono, category=category, **data)


def test_monthly_amount_by_period(home, mono, home_subs):
    weekly = payment(home, mono, home_subs, amount=Decimal("120"), period="weekly")
    yearly = payment(home, mono, home_subs, amount=Decimal("1200"), period="yearly")

    assert monthly_amount(weekly, TODAY) == Decimal("520")
    assert monthly_amount(yearly, TODAY) == Decimal("100")


def test_occurrences_and_first_date(home, mono, home_subs):
    weekly = payment(home, mono, home_subs, period="weekly", start_date=datetime.date(2026, 10, 1))

    assert first_date_from(weekly, TODAY) == datetime.date(2026, 10, 22)
    weekly.next_date = datetime.date(2026, 10, 22)
    assert occurrences(weekly, TODAY, datetime.date(2026, 10, 31)) == [datetime.date(2026, 10, 22), datetime.date(2026, 10, 29)]


def test_page_groups_and_totals(yura_client, home, mono, home_subs, salary):
    today = timezone.localdate()
    payment(home, mono, home_subs, title="Скоро", start_date=today + datetime.timedelta(days=2))
    payment(home, mono, home_subs, title="Пізніше", start_date=today + datetime.timedelta(days=40))
    payment(home, mono, home_subs, title="Пауза", is_active=False)
    payment(home, mono, salary, title="Зарплата", type="income", amount=Decimal("30000"))

    response = yura_client.get(reverse("recurring:payments"))

    groups = {g["key"]: [p.title for p in g["items"]] for g in response.context["groups"]}
    assert "Скоро" in groups["week"]
    assert groups["later"] == ["Пізніше"]
    assert groups["paused"] == ["Пауза"]
    assert response.context["monthly"] == Decimal("398")


def test_create_payment_from_today(yura_client, home, mono, home_subs):
    yura_client.post(reverse("recurring:payment_create"), {
        "type": "expense", "title": "Інтернет", "amount": "250", "account": mono.pk, "category": home_subs.pk,
        "period": "monthly", "start_date": "2026-01-15", "member": "",
    })

    created = home.recurring_payments.get(title="Інтернет")
    assert created.next_date >= timezone.localdate()
    assert created.next_date.day == 15


def test_category_must_match_type(yura_client, home, mono, home_subs):
    response = yura_client.post(reverse("recurring:payment_create"), {
        "type": "income", "title": "Дивно", "amount": "250", "account": mono.pk, "category": home_subs.pk,
        "period": "monthly", "start_date": "2026-11-01",
    })

    assert "category" in response.context["form"].errors


def test_edit_keeps_schedule_unless_start_changes(yura_client, home, mono, home_subs):
    item = payment(home, mono, home_subs, start_date=datetime.date(2026, 11, 5))
    url = reverse("recurring:payment_edit", args=[item.pk])
    data = {
        "type": "expense", "title": "Spotify Family", "amount": "299", "account": mono.pk, "category": home_subs.pk,
        "period": "monthly", "start_date": "2026-11-05", "member": "",
    }

    yura_client.post(url, data)
    item.refresh_from_db()
    assert (item.title, item.next_date) == ("Spotify Family", datetime.date(2026, 11, 5))

    yura_client.post(url, {**data, "start_date": "2026-11-20"})
    item.refresh_from_db()
    assert item.next_date == datetime.date(2026, 11, 20)


def test_pay_now_creates_transaction_and_moves_date(yura_client, home, mono, home_subs):
    item = payment(home, mono, home_subs, start_date=datetime.date(2026, 11, 5), is_approximate=True)

    yura_client.post(reverse("recurring:payment_pay", args=[item.pk]), {"amount": "215,50", "date": "2026-10-22"})

    tx = home.transactions.get(title="Spotify")
    assert (tx.amount, tx.date, tx.source) == (Decimal("215.50"), datetime.date(2026, 10, 22), Transaction.Source.RECURRING)
    item.refresh_from_db()
    assert item.next_date == datetime.date(2026, 12, 5)


def test_pause_and_resume(yura_client, home, mono, home_subs):
    item = payment(home, mono, home_subs, start_date=datetime.date(2026, 1, 1))
    url = reverse("recurring:payment_toggle", args=[item.pk])

    yura_client.post(url)
    item.refresh_from_db()
    assert not item.is_active
    assert yura_client.get(reverse("recurring:payment_pay", args=[item.pk])).status_code == 404

    yura_client.post(url)
    item.refresh_from_db()
    assert item.is_active
    assert item.next_date >= timezone.localdate()


def test_delete_keeps_transactions(yura_client, home, mono, home_subs):
    item = payment(home, mono, home_subs)
    yura_client.post(reverse("recurring:payment_pay", args=[item.pk]), {"amount": "199", "date": "2026-10-22"})

    yura_client.post(reverse("recurring:payment_delete", args=[item.pk]))

    assert not home.recurring_payments.exists()
    assert home.transactions.filter(title="Spotify").exists()


def test_foreign_payment_is_hidden(yura_client, user):
    stranger = create_household(user, "Чужий дім")
    account = stranger.accounts.create(name="Чужа")
    item = payment(stranger, account, stranger.categories.filter(kind="expense").first())

    assert yura_client.get(reverse("recurring:payment_edit", args=[item.pk])).status_code == 404
    assert yura_client.post(reverse("recurring:payment_delete", args=[item.pk])).status_code == 404
    assert yura_client.post(reverse("recurring:payment_toggle", args=[item.pk])).status_code == 404


def test_overview_shows_upcoming(yura_client, home, mono, home_subs):
    payment(home, mono, home_subs, title="Завтра", start_date=timezone.localdate() + datetime.timedelta(days=1))
    payment(home, mono, home_subs, title="Далеко", start_date=timezone.localdate() + datetime.timedelta(days=20))

    response = yura_client.get(reverse("core:home"))

    assert [p.title for p in response.context["upcoming"]] == ["Завтра"]


def test_left_this_month_follows_budget_month(yura_client, home, mono, home_subs):
    home.month_start_day = 20
    home.save()
    period = home.period(timezone.localdate())
    payment(home, mono, home_subs, title="Квартира", amount=Decimal("12000"), start_date=period.end)
    payment(home, mono, home_subs, title="Наступного місяця", amount=Decimal("500"), start_date=period.end + datetime.timedelta(days=1))

    response = yura_client.get(reverse("recurring:payments"))

    assert response.context["left_this_month"] == Decimal("12000")
