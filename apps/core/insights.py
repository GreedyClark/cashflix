import math
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import ExtractIsoWeekDay
from django.utils import formats
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.templatetags.money import money

ZERO = Decimal("0")
HISTORY_MONTHS = 3
SPIKE = Decimal("1.3")
DROP = Decimal("0.7")
MIN_DIFFERENCE = Decimal("500")
MIN_EXPENSES = 3
WEEKDAYS = [
    gettext_lazy("понеділок"), gettext_lazy("вівторок"), gettext_lazy("середу"), gettext_lazy("четвер"),
    gettext_lazy("п'ятницю"), gettext_lazy("суботу"), gettext_lazy("неділю"),
]


@dataclass
class Insight:
    tone: str
    icon: str
    text: str
    weight: int


def by_category(queryset):
    rows = queryset.order_by().values("category").annotate(total=Sum("amount_base")).values_list("category", "total")
    return dict(rows)


class Insights:
    def __init__(self, overview):
        self.overview = overview
        self.today = overview.today
        self.currency = overview.household.base_currency

    def money(self, value):
        return money(value, self.currency)

    def usual_by_category(self):
        totals = {}
        for offset in range(1, HISTORY_MONTHS + 1):
            past = self.overview.period.shift(-offset)
            period = self.overview.transactions.between(past.start, self.overview.same_days_of(past)).expenses()
            for category, total in by_category(period).items():
                totals[category] = totals.get(category, ZERO) + total
        return {category: total / HISTORY_MONTHS for category, total in totals.items()}

    def categories(self):
        usual = self.usual_by_category()
        now = by_category(self.overview.this_month.expenses())
        names = dict(self.overview.household.categories.values_list("pk", "name"))
        found = []
        for category in set(usual) | set(now):
            before, current = usual.get(category, ZERO), now.get(category, ZERO)
            if not before or abs(current - before) < MIN_DIFFERENCE:
                continue
            percent = round(abs(current - before) / before * 100)
            name = names.get(category, _("Без категорії"))
            if current > before * SPIKE:
                text = _("На «%(name)s» цього місяця вже %(amount)s, на %(percent)s%% більше, ніж зазвичай на цей день.")
                found.append(Insight("warn", "trending-up", text % {"name": name, "amount": self.money(current), "percent": percent}, 80 + min(percent, 100) // 10))
            elif current < before * DROP:
                text = _("На «%(name)s» витрачено на %(percent)s%% менше, ніж зазвичай: %(amount)s замість %(usual)s.")
                found.append(Insight("good", "trending-down", text % {"name": name, "percent": percent, "amount": self.money(current), "usual": self.money(before)}, 50))
        return sorted(found, key=lambda item: item.weight, reverse=True)[:2]

    def forecast(self):
        overview = self.overview
        if overview.day < 5 or not overview.income_forecast:
            return []
        result = overview.income_forecast - overview.saved - overview.forecast_total
        if result >= 0:
            text = _("Якщо тримати такий темп, місяць закриєте з плюсом приблизно %(amount)s.")
            return [Insight("good", "pig-money", text % {"amount": self.money(result)}, 60)]
        text = _("За нинішнього темпу витрати перевищать дохід місяця приблизно на %(amount)s.")
        return [Insight("warn", "report-money", text % {"amount": self.money(-result)}, 90)]

    def limits(self):
        found = []
        days_left = self.overview.days_in_month - self.overview.day
        for item in self.overview.limits():
            spent, limit, amount = item["spent"], item["limit"], item["amount"]
            if spent >= amount or not spent or days_left <= 0:
                continue
            per_day = spent / self.overview.day
            days_to_limit = math.ceil((amount - spent) / per_day)
            if days_to_limit < days_left:
                date = self.today + timedelta(days=days_to_limit)
                text = _("Ліміт на «%(name)s» за такого темпу закінчиться приблизно %(date)s.")
                found.append(Insight("warn", "clock", text % {"name": limit.category.name, "date": formats.date_format(date, "j E")}, 85))
        return found[:1]

    def weekday(self):
        start = self.today - timedelta(days=90)
        rows = (
            self.overview.transactions.expenses()
            .between(start, self.today)
            .annotate(weekday=ExtractIsoWeekDay("date"))
            .order_by()
            .values("weekday")
            .annotate(total=Sum("amount_base"))
        )
        totals = {row["weekday"]: row["total"] for row in rows}
        if len(totals) < 7:
            return []
        average = sum(totals.values()) / 7
        weekday, total = max(totals.items(), key=lambda item: item[1])
        if total < average * Decimal("1.4"):
            return []
        weeks = Decimal("90") / 7
        text = _("Найбільше витрачаєте в %(day)s: у середньому %(amount)s за день.")
        return [Insight("info", "calendar", text % {"day": WEEKDAYS[weekday - 1], "amount": self.money(total / weeks)}, 30)]

    def biggest(self):
        expenses = self.overview.this_month.expenses()
        if expenses.count() < MIN_EXPENSES:
            return []
        tx = expenses.select_related("category").order_by("-amount_base").first()
        if not self.overview.spent or tx.amount_base < self.overview.spent * Decimal("0.15"):
            return []
        name = tx.category.name if tx.category else _("Без категорії")
        text = _("Найбільша разова витрата місяця: %(amount)s на «%(name)s». Це %(share)s%% усіх витрат.")
        share = round(tx.amount_base / self.overview.spent * 100)
        return [Insight("info", "receipt", text % {"name": name, "amount": self.money(tx.amount_base), "share": share}, 40)]

    def all(self, count=4):
        found = self.limits() + self.forecast() + self.categories() + self.biggest() + self.weekday()
        return sorted(found, key=lambda item: item.weight, reverse=True)[:count]
