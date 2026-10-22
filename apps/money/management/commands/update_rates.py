from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.money.nbu import NbuUnavailable, save_rates


class Command(BaseCommand):
    help = "Downloads USD and EUR rates from the National Bank of Ukraine"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=1, help="How many days back to load, including today")

    def handle(self, *args, **options):
        today = timezone.localdate()
        for offset in range(options["days"]):
            day = today - timedelta(days=offset)
            try:
                rates = save_rates(day)
            except NbuUnavailable as error:
                raise CommandError(f"НБУ недоступний: {error}") from error
            text = ", ".join(f"{currency} {rate}" for currency, rate in sorted(rates.items()))
            self.stdout.write(f"{day:%d.%m.%Y}: {text}")
