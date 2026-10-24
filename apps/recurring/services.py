import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.money.rates import RateNotFound, convert_rate

from .models import RecurringPayment

logger = logging.getLogger(__name__)


def run_due_payments(today=None):
    today = today or timezone.localdate()
    created = []

    due = RecurringPayment.objects.filter(
        is_active=True, mode=RecurringPayment.Mode.AUTO, next_date__lte=today
    ).select_related(
        "household", "account", "category"
    )
    for payment in due:
        try:
            with transaction.atomic():
                while payment.next_date <= today:
                    tx = payment.make_transaction(payment.next_date)
                    tx.save()
                    created.append(tx)
                    payment.next_date = payment.following_date(payment.next_date)
                payment.save(update_fields=["next_date"])
        except RateNotFound:
            logger.warning("Skipped recurring payment %s: no exchange rate yet", payment.pk)

    return created

PER_MONTH = {
    RecurringPayment.Period.WEEKLY: Decimal("52") / 12,
    RecurringPayment.Period.MONTHLY: Decimal("1"),
    RecurringPayment.Period.YEARLY: Decimal("1") / 12,
}


def in_base(payment, amount, today):
    base = payment.household.base_currency
    try:
        return amount * convert_rate(payment.pay_currency, base, today)
    except RateNotFound:
        return None


def monthly_amount(payment, today):
    value = in_base(payment, payment.amount, today)
    return None if value is None else value * PER_MONTH[payment.period]


def occurrences(payment, start, end):
    dates = []
    date = payment.next_date
    while date <= end:
        if date >= start:
            dates.append(date)
        date = payment.following_date(date)
    return dates


def first_date_from(payment, today):
    date = payment.start_date
    while date < today:
        date = payment.following_date(date)
    return date


@transaction.atomic
def pay_now(payment, amount, date):
    tx = payment.make_transaction(date, account_amount=amount)
    tx.save()
    payment.next_date = payment.following_date(payment.next_date)
    payment.save(update_fields=["next_date"])
    return tx
