from django.utils import timezone

from apps.money.models import ExchangeRate
from apps.money.nbu import NbuUnavailable, save_rates
from apps.notifications.reminders import send_reminders
from apps.recurring.services import run_due_payments


def run_daily(now=None):
    today = timezone.localdate(now)
    report = []
    if ExchangeRate.objects.filter(date=today).exists():
        report.append("Rates: already saved today")
    else:
        try:
            rates = save_rates(today)
            report.append("Rates: " + ", ".join(f"{code} {rate}" for code, rate in sorted(rates.items())))
        except NbuUnavailable as error:
            report.append(f"NBU unavailable: {error}")
    created = run_due_payments()
    report.append(f"Recurring: created {len(created)} transaction(s)")
    report.append(f"Reminders: sent to {send_reminders(now)} person(s)")
    return report
