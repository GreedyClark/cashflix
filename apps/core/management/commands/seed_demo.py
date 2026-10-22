import datetime
import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.budgets.models import Limit
from apps.goals.models import Goal, GoalContribution
from apps.households.models import Household
from apps.households.services import add_member, create_household
from apps.money.models import Account, AccountValuation, ExchangeRate, Transaction
from apps.recurring.dates import add_months
from apps.recurring.models import RecurringPayment
from apps.recurring.services import run_due_payments

User = get_user_model()

HOUSEHOLD_NAME = "Дім (демо)"
PASSWORD = "demo12345"
USERS = [
    ("yura@demo.cashflix", "Юра"),
    ("olya@demo.cashflix", "Олічка"),
]

# category: (merchants, typical amount, purchases per week)
SPENDING = {
    "Продукти": (["Сільпо", "АТБ", "Новус", "Фора"], 520, 5),
    "Кафе": (["Aroma Kava", "Пузата хата", "Lviv Croissants"], 180, 3),
    "Транспорт": (["Uklon", "Bolt", "WOG"], 220, 3),
    "Розваги": (["Multiplex", "Steam", "Планетарій"], 350, 0.7),
    "Одяг": (["Zara", "Reserved", "Intertop"], 1400, 0.4),
    "Здоров'я": (["Аптека АНЦ", "Подорожник"], 300, 0.6),
    "Інше": (["Нова пошта", "Rozetka"], 260, 0.8),
}


class Command(BaseCommand):
    help = "Fills the database with a demo household for local development"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete the previous demo data first")
        parser.add_argument("--months", type=int, default=6)

    @transaction.atomic
    def handle(self, *args, **options):
        if Household.objects.filter(name=HOUSEHOLD_NAME).exists():
            if not options["reset"]:
                self.stdout.write(self.style.WARNING("Demo data already exists. Use --reset to recreate it."))
                return
            self.reset()

        self.rng = random.Random(42)
        self.today = timezone.localdate()
        self.start = add_months(self.today.replace(day=1), -(options["months"] - 1))

        self.create_rates()
        yura, olya = self.create_people()
        self.home = create_household(yura, HOUSEHOLD_NAME)
        self.yura = self.home.memberships.get(user=yura)
        self.olya = add_member(self.home, olya)
        self.categories = {c.name: c for c in self.home.categories.filter(kind="expense")}
        self.income_categories = {c.name: c for c in self.home.categories.filter(kind="income")}

        self.create_accounts()
        count = self.create_transactions()
        self.create_limits()
        self.create_recurring()
        self.create_goals()
        self.create_valuations()

        self.stdout.write(self.style.SUCCESS(f"Demo household created with {count} transactions."))
        for email, _ in USERS:
            self.stdout.write(f"  {email} / {PASSWORD}")

    def reset(self):
        household = Household.objects.get(name=HOUSEHOLD_NAME)
        household.transactions.all().delete()
        household.recurring_payments.all().delete()
        household.delete()
        User.objects.filter(email__in=[email for email, _ in USERS]).delete()

    def create_people(self):
        people = []
        for email, name in USERS:
            user = User.objects.create_user(email=email, password=PASSWORD, display_name=name)
            people.append(user)
        return people

    def create_rates(self):
        day = self.start - datetime.timedelta(days=7)
        usd, eur = Decimal("41.10"), Decimal("44.80")
        while day <= self.today:
            if day.weekday() < 5:
                usd += Decimal(self.rng.uniform(-0.08, 0.09)).quantize(Decimal("0.0001"))
                eur += Decimal(self.rng.uniform(-0.1, 0.11)).quantize(Decimal("0.0001"))
                ExchangeRate.objects.update_or_create(currency="USD", date=day, defaults={"rate": usd})
                ExchangeRate.objects.update_or_create(currency="EUR", date=day, defaults={"rate": eur})
            day += datetime.timedelta(days=1)

    def create_accounts(self):
        common = {"household": self.home}
        self.mono = Account.objects.create(name="Монобанк", owner=self.yura, opening_balance=Decimal("12000"), **common)
        self.privat = Account.objects.create(name="ПриватБанк", owner=self.olya, opening_balance=Decimal("8000"), **common)
        self.cash = Account.objects.create(name="Готівка", kind=Account.Kind.CASH, opening_balance=Decimal("1500"), **common)
        self.usd = Account.objects.create(
            name="Доларовий", kind=Account.Kind.SAVINGS, currency="USD", opening_balance=Decimal("300"), **common
        )
        self.fund = Account.objects.create(
            name="Фонд нерухомості",
            kind=Account.Kind.INVESTMENT,
            investment_type="Фонд нерухомості",
            yield_mode=Account.YieldMode.MARKET,
            owner=self.yura,
            opening_balance=Decimal("20000"),
            **common,
        )
        self.bonds = Account.objects.create(
            name="ОВДП до 2027",
            kind=Account.Kind.INVESTMENT,
            investment_type="ОВДП",
            yield_mode=Account.YieldMode.FIXED,
            annual_rate=Decimal("16"),
            starts_on=self.today - datetime.timedelta(days=95),
            ends_on=self.today + datetime.timedelta(days=270),
            payout=Account.Payout.END,
            owner=self.olya,
            opening_balance=Decimal("50000"),
            **common,
        )

    def add(self, **fields):
        tx = Transaction(household=self.home, **fields)
        tx.save()
        return tx

    def create_transactions(self):
        count = 0
        day = self.start
        while day <= self.today:
            for category_name, (merchants, typical, per_week) in SPENDING.items():
                if self.rng.random() < per_week / 7:
                    member = self.rng.choice([self.yura, self.olya])
                    account = self.mono if member == self.yura else self.privat
                    if self.rng.random() < 0.1:
                        account = self.cash
                    amount = Decimal(round(typical * self.rng.uniform(0.4, 1.8)))
                    self.add(
                        date=day,
                        title=self.rng.choice(merchants),
                        category=self.categories[category_name],
                        account=account,
                        member=member,
                        amount=amount,
                    )
                    count += 1

            if day.day == 10:
                self.add(
                    type=Transaction.Type.INCOME,
                    date=day,
                    title="Зарплата",
                    category=self.income_categories["Зарплата"],
                    account=self.privat,
                    member=self.olya,
                    amount=Decimal("31000"),
                )
                count += 1
            if day.day == 13:
                self.add(
                    type=Transaction.Type.INCOME,
                    date=day,
                    title="Зарплата",
                    category=self.income_categories["Зарплата"],
                    account=self.mono,
                    member=self.yura,
                    amount=Decimal("31000"),
                )
                self.add(
                    type=Transaction.Type.TRANSFER,
                    date=day,
                    title="Монобанк → Готівка",
                    account=self.mono,
                    to_account=self.cash,
                    member=self.yura,
                    amount=Decimal("2000"),
                )
                count += 2
            if day.day == 15:
                self.add(
                    type=Transaction.Type.TRANSFER,
                    date=day,
                    title="Поповнення інвестицій",
                    account=self.mono,
                    to_account=self.fund,
                    member=self.yura,
                    amount=Decimal("3000"),
                )
                count += 1
            day += datetime.timedelta(days=1)
        return count

    def create_valuations(self):
        invested = self.fund.opening_balance
        month = self.start
        while month <= self.today:
            invested += Decimal("3000")
            growth = Decimal("1.004") ** ((month.year - self.start.year) * 12 + month.month - self.start.month + 1)
            AccountValuation.objects.create(
                account=self.fund, date=month.replace(day=28) if month.month != self.today.month else self.today,
                value=(invested * growth).quantize(Decimal("1")),
            )
            month = add_months(month, 1)

    def create_limits(self):
        rows = [
            ("Продукти", None, "10000"),
            ("Кафе", None, "3000"),
            ("Одяг", self.olya, "4000"),
            ("Розваги", self.yura, "2000"),
            ("Транспорт", self.yura, "2500"),
        ]
        for category_name, member, amount in rows:
            Limit.objects.create(
                household=self.home, category=self.categories[category_name], member=member, amount=Decimal(amount)
            )

    def create_recurring(self):
        rows = [
            ("Комунальні послуги", "Комуналка", self.privat, "2300", 16, True, True),
            ("Spotify", "Підписки", self.privat, "199", 18, False, True),
            ("Інтернет Київстар", "Комуналка", self.mono, "250", 20, False, True),
            ("iCloud", "Підписки", self.mono, "99", 8, False, True),
            ("Netflix", "Підписки", self.usd, "8.99", 13, False, True),
            ("Спортзал", "Розваги", self.mono, "900", 1, False, False),
        ]
        for title, category_name, account, amount, day, approximate, active in rows:
            RecurringPayment.objects.create(
                household=self.home,
                title=title,
                category=self.categories[category_name],
                account=account,
                amount=Decimal(amount),
                is_approximate=approximate,
                start_date=self.start.replace(day=day),
                is_active=active,
            )
        run_due_payments(self.today)

    def create_goals(self):
        rows = [
            ("Відпустка влітку", "beach", 1, "60000", add_months(self.today, 8), [3000, 4500, 2000, 5000, 3900, 5000]),
            ("Подушка безпеки", "shield-check", 3, "120000", add_months(self.today, 5), [8000, 6000, 9000, 7000, 6500, 7500]),
            ("Новий ноутбук", "device-laptop", 7, "45000", add_months(self.today, 2), [4000, 5000, 6000, 5000, 6000, 5000]),
        ]
        for name, icon, color, target, deadline, history in rows:
            goal = Goal.objects.create(
                household=self.home, name=name, icon=icon, color_slot=color, target_amount=Decimal(target),
                deadline=deadline,
            )
            for months_ago, amount in enumerate(reversed(history)):
                GoalContribution.objects.create(
                    goal=goal,
                    date=add_months(self.today.replace(day=1), -months_ago),
                    amount=Decimal(amount),
                    member=self.rng.choice([self.yura, self.olya]),
                )
        Goal.objects.create(
            household=self.home, name="Долари на чорний день", icon="currency-dollar", color_slot=4,
            target_amount=Decimal("1000"), account=self.usd,
        )