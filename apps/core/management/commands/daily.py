from django.core.management.base import BaseCommand

from apps.core.daily import run_daily


class Command(BaseCommand):
    help = "Daily jobs: NBU rates and recurring payments"

    def handle(self, *args, **options):
        for line in run_daily():
            self.stdout.write(line)
