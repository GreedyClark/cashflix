import calendar
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import dateformat

from apps.budgets.summary import BudgetMonth
from apps.core.templatetags.money import money
from apps.goals.services import goal_items
from apps.money.models import Transaction
from apps.recurring.dates import add_months
from apps.recurring.services import monthly_amount

ZERO = Decimal("0")
MONTHS = 4


def line(label, value):
    return f"- {label}: {value}"


def months_block(household, today, currency):
    start = add_months(today.replace(day=1), -(MONTHS - 1))
    rows = (
        household.transactions.filter(date__gte=start, date__lte=today)
        .exclude(type=Transaction.Type.TRANSFER)
        .annotate(period=TruncMonth("date"))
        .values("period", "type")
        .annotate(total=Sum("amount_base"))
    )
    totals = {(row["period"], row["type"]): row["total"] for row in rows}
    lines = ["Доходи й витрати по місяцях:"]
    for offset in range(MONTHS):
        month = add_months(start, offset)
        earned = totals.get((month, Transaction.Type.INCOME), ZERO)
        spent = totals.get((month, Transaction.Type.EXPENSE), ZERO)
        suffix = f" (поточний, день {today.day} з {calendar.monthrange(today.year, today.month)[1]})" if month.month == today.month and month.year == today.year else ""
        lines.append(line(f"{dateformat.format(month, 'F Y')}{suffix}", f"дохід {money(earned, currency)}, витрати {money(spent, currency)}"))
    return lines


def categories_block(household, today, currency):
    month = today.replace(day=1)
    previous = add_months(month, -1)
    lines = ["Витрати по категоріях, цей місяць (минулий місяць повністю):"]
    current = by_category(household, month, today)
    before = by_category(household, previous, month - timedelta(days=1))
    for name in sorted(set(current) | set(before), key=lambda key: current.get(key, ZERO), reverse=True):
        lines.append(line(name, f"{money(current.get(name, ZERO), currency)} ({money(before.get(name, ZERO), currency)})"))
    return lines


def by_category(household, start, end):
    rows = (
        household.transactions.expenses().between(start, end).order_by()
        .values("category__name").annotate(total=Sum("amount_base"))
    )
    return {row["category__name"] or "Без категорії": row["total"] for row in rows}


def limits_block(household, today, currency):
    budget = BudgetMonth(household, today.replace(day=1), today)
    limits = budget.limits()
    if not limits:
        return ["Лімітів немає."]
    lines = [f"Ліміти на цей місяць (минуло {budget.pace}% місяця):"]
    for item in limits:
        limit = item["limit"]
        who = "спільний" if limit.is_shared else "особистий"
        lines.append(line(
            f"{limit.category.name} ({who})",
            f"ліміт {money(limit.amount, currency)}, витрачено {money(item['spent'], currency)} ({item['percent']}%)",
        ))
    return lines


def recurring_block(household, today, currency):
    payments = household.recurring_payments.filter(is_active=True, type=Transaction.Type.EXPENSE).select_related("account", "household", "category")
    if not payments:
        return ["Регулярних платежів немає."]
    total = sum((monthly_amount(payment, today) or ZERO for payment in payments), ZERO)
    lines = [f"Регулярні платежі: {len(payments)} шт., разом {money(total, currency)} на місяць. По категоріях:"]
    per_category = {}
    for payment in payments:
        per_category[payment.category.name] = per_category.get(payment.category.name, ZERO) + (monthly_amount(payment, today) or ZERO)
    lines += [line(name, money(amount, currency)) for name, amount in per_category.items()]
    return lines


def goals_block(household, today):
    items = goal_items(household, today)
    if not items:
        return ["Цілей немає."]
    lines = ["Цілі:"]
    for item in items:
        goal = item["goal"]
        parts = [f"відкладено {money(item['saved'], goal.currency)} з {money(goal.target_amount, goal.currency)} ({item['progress']}%)"]
        if goal.deadline:
            parts.append(f"до {dateformat.format(goal.deadline, 'j E Y')}")
        if item["monthly"]:
            parts.append(f"треба {money(item['monthly'], goal.currency)} на місяць")
        lines.append(line(goal.name, ", ".join(parts)))
    return lines


def build_briefing(household, today):
    currency = household.base_currency
    blocks = [
        [f"Сьогодні {dateformat.format(today, 'j E Y')}. Основна валюта {currency}."],
        months_block(household, today, currency),
        categories_block(household, today, currency),
        limits_block(household, today, currency),
        recurring_block(household, today, currency),
        goals_block(household, today),
    ]
    return "\n\n".join("\n".join(block) for block in blocks)
