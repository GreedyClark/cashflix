from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.money.nbu import NbuUnavailable, save_rates
from apps.recurring.services import run_due_payments


class Command(BaseCommand):
    help = "Daily jobs: NBU rates and recurring payments"

    def handle(self, *args, **options):
        try:
            rates = save_rates(timezone.localdate())
            self.stdout.write("Rates: " + ", ".join(f"{code} {rate}" for code, rate in sorted(rates.items())))
        except NbuUnavailable as error:
            self.stderr.write(f"NBU unavailable: {error}")
        created = run_due_payments()
        self.stdout.write(f"Recurring: created {len(created)} transaction(s)")
