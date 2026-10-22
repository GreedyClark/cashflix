from django.utils import timezone

from apps.money.nbu import NbuUnavailable, save_rates
from apps.recurring.services import run_due_payments


def run_daily():
    report = []
    try:
        rates = save_rates(timezone.localdate())
        report.append("Rates: " + ", ".join(f"{code} {rate}" for code, rate in sorted(rates.items())))
    except NbuUnavailable as error:
        report.append(f"NBU unavailable: {error}")
    created = run_due_payments()
    report.append(f"Recurring: created {len(created)} transaction(s)")
    return report
