import datetime
from decimal import Decimal

from apps.money.models import Transaction
from apps.recurring.dates import add_months
from apps.recurring.models import RecurringPayment
from apps.recurring.services import run_due_payments


def test_add_months_keeps_day_when_possible():
    assert add_months(datetime.date(2026, 1, 31), 1) == datetime.date(2026, 2, 28)
    assert add_months(datetime.date(2026, 2, 28), 1, day=31) == datetime.date(2026, 3, 31)
    assert add_months(datetime.date(2026, 11, 15), 3) == datetime.date(2027, 2, 15)


def test_next_date_defaults_to_start_date(home, mono, home_subs):
    payment = RecurringPayment.objects.create(
        household=home, title="Spotify", account=mono, category=home_subs, amount=Decimal("199"),
        start_date=datetime.date(2026, 10, 18),
    )

    assert payment.next_date == datetime.date(2026, 10, 18)


def test_run_creates_missed_payments_and_moves_next_date(home, mono, home_subs):
    payment = RecurringPayment.objects.create(
        household=home, title="Spotify", account=mono, category=home_subs, amount=Decimal("199"),
        start_date=datetime.date(2026, 8, 31),
    )

    created = run_due_payments(today=datetime.date(2026, 10, 16))

    assert [tx.date for tx in created] == [datetime.date(2026, 8, 31), datetime.date(2026, 9, 30)]
    assert all(tx.source == Transaction.Source.RECURRING for tx in created)
    payment.refresh_from_db()
    assert payment.next_date == datetime.date(2026, 10, 31)


def test_inactive_payments_are_skipped(home, mono, home_subs):
    RecurringPayment.objects.create(
        household=home, title="Спортзал", account=mono, category=home_subs, amount=Decimal("900"),
        start_date=datetime.date(2026, 10, 1), is_active=False,
    )

    assert run_due_payments(today=datetime.date(2026, 10, 16)) == []


def test_payment_without_rate_waits(home, usd_account, home_subs):
    payment = RecurringPayment.objects.create(
        household=home, title="Netflix", account=usd_account, category=home_subs, amount=Decimal("8.99"),
        start_date=datetime.date(2026, 10, 13),
    )

    assert run_due_payments(today=datetime.date(2026, 10, 16)) == []
    payment.refresh_from_db()
    assert payment.next_date == datetime.date(2026, 10, 13)