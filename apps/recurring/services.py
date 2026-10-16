import logging

from django.db import transaction
from django.utils import timezone

from apps.money.rates import RateNotFound

from .models import RecurringPayment

logger = logging.getLogger(__name__)


def run_due_payments(today=None):
    today = today or timezone.localdate()
    created = []

    due = RecurringPayment.objects.filter(is_active=True, next_date__lte=today).select_related(
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