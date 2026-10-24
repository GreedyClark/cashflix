from decimal import Decimal

from django.db.models import Sum
from django.utils import dateformat

from apps.budgets.summary import BudgetMonth
from apps.core.templatetags.money import money
from apps.goals.services import goal_items
from apps.money.models import Transaction
from apps.recurring.services import monthly_amount

ZERO = Decimal("0")
MONTHS = 4


def line(label, value):
    return f"- {label}: {value}"


def months_block(household, today, currency):
    current = household.period(today)
    lines = ["Доходи й витрати по бюджетних місяцях:"]
    if not current.is_calendar:
        lines[0] = f"Бюджетний місяць у сім'ї починається {household.month_start_day}-го числа. Доходи й витрати по бюджетних місяцях:"
    for offset in range(-(MONTHS - 1), 1):
        period = current.shift(offset)
        until = min(period.end, today)
        income_start, income_end = period.income_range()
        earned = household.transactions.incomes().between(income_start, min(income_end, today)).total_base()
        spent = household.transactions.expenses().between(period.start, until).total_base()
        suffix = f" (поточний, день {period.day_number(today)} з {period.days})" if offset == 0 else ""
        lines.append(line(f"{period.label}{suffix}", f"дохід {money(earned, currency)}, витрати {money(spent, currency)}"))
    return lines


def categories_block(household, today, currency):
    current = household.period(today)
    previous = current.previous()
    lines = ["Витрати по категоріях, цей бюджетний місяць (минулий повністю):"]
    now = by_category(household, current.start, today)
    before = by_category(household, previous.start, previous.end)
    for name in sorted(set(now) | set(before), key=lambda key: now.get(key, ZERO), reverse=True):
        lines.append(line(name, f"{money(now.get(name, ZERO), currency)} ({money(before.get(name, ZERO), currency)})"))
    return lines


def by_category(household, start, end):
    rows = (
        household.transactions.expenses().between(start, end).order_by()
        .values("category__name").annotate(total=Sum("amount_base"))
    )
    return {row["category__name"] or "Без категорії": row["total"] for row in rows}


def limits_block(household, today, currency):
    budget = BudgetMonth(household, household.period(today), today)
    limits = budget.limits()
    family = budget.income.family
    lines = [f"Дохід цього бюджетного місяця: прийшло {money(family.received, currency)}, ще очікується {money(family.expected, currency)}."]
    if not limits:
        return lines + ["Лімітів немає."]
    lines.append(f"Ліміти на цей місяць (минуло {budget.pace}% місяця):")
    for item in limits:
        limit = item["limit"]
        who = "спільний" if limit.is_shared else "особистий"
        size = money(item["amount"], currency)
        if limit.is_percent:
            size += f" ({limit.percent.normalize()}% доходу, з усім доходом буде {money(item['full'], currency)})"
        lines.append(line(
            f"{limit.category.name} ({who})",
            f"ліміт {size}, витрачено {money(item['spent'], currency)} ({item['percent']}%)",
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
