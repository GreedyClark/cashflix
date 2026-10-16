from django.core.management.base import BaseCommand

from apps.recurring.services import run_due_payments


class Command(BaseCommand):
    help = "Creates transactions for recurring payments that are due"

    def handle(self, *args, **options):
        created = run_due_payments()
        self.stdout.write(self.style.SUCCESS(f"Created {len(created)} transaction(s)"))