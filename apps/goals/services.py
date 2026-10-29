from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import Max

from apps.money.accounts import load_accounts
from apps.money.models import Account, Transaction
from apps.money.rates import convert_amount as convert

from .models import GoalContribution

ZERO = Decimal("0")
RESERVE_NAME = "Відкладено на цілі"


def account_values(household, today, goals):
    linked = {goal.account_id for goal in goals if goal.account_id}
    if not linked:
        return {}
    values = {account.pk: account.value for account in load_accounts(household, today) if account.pk in linked}
    missing = linked - set(values)
    for account in Account.objects.with_balance().filter(pk__in=missing):
        values[account.pk] = account.balance
    return values


def contributions_saved(goals):
    manual = {goal.pk: goal for goal in goals if not goal.tracks_account}
    totals = {}
    for contribution in GoalContribution.objects.filter(goal__in=manual):
        contribution.goal = manual[contribution.goal_id]
        totals[contribution.goal_id] = totals.get(contribution.goal_id, ZERO) + contribution.in_goal_currency()
    return totals


def goal_items(household, today, archived=False):
    goals = list(
        household.goals.filter(is_archived=archived)
        .select_related("account", "household")
        .annotate(last_date=Max("contributions__date"))
    )
    values = account_values(household, today, goals)
    contributed = contributions_saved(goals)
    items = []
    for goal in goals:
        saved = values.get(goal.account_id, ZERO) if goal.tracks_account else contributed.get(goal.pk, ZERO)
        items.append({
            "goal": goal,
            "saved": saved,
            "left": max(ZERO, goal.target_amount - saved),
            "progress": goal.progress(saved),
            "monthly": goal.monthly_needed(saved, today),
            "plan": goal.monthly_plan(saved, today),
            "done": saved >= goal.target_amount,
            "overdue": bool(goal.deadline and goal.deadline < today and saved < goal.target_amount),
        })
    return items


LIVE = (Account.Kind.CARD, Account.Kind.CASH)
TYPICAL_MONTHS = 3


def reserve_account(household, currency):
    name = RESERVE_NAME if currency == household.base_currency else f"{RESERVE_NAME} {currency}"
    account = household.accounts.filter(kind=Account.Kind.SAVINGS, currency=currency, name=name).first()
    if account:
        if account.is_archived:
            account.is_archived = False
            account.save(update_fields=["is_archived"])
        return account
    return Account.objects.create(household=household, name=name, kind=Account.Kind.SAVINGS, currency=currency)


def move(household, source, target, amount_in_target, on_date, member, title):
    return Transaction.objects.create(
        household=household,
        type=Transaction.Type.TRANSFER,
        date=on_date,
        title=title,
        account=source,
        to_account=target,
        amount=convert(amount_in_target, target.currency, source.currency, on_date),
        to_amount=amount_in_target,
        member=member,
    )


@db_transaction.atomic
def contribute(goal, *, amount, taking, on_date, member, note="", source=None, currency=None):
    household = goal.household
    currency = currency or goal.currency
    title = f"{'З цілі' if taking else 'У ціль'}: {goal.name}"
    if goal.tracks_account:
        if taking:
            return move(household, goal.account, source, convert(amount, goal.currency, source.currency, on_date), on_date, member, title)
        return move(household, source, goal.account, amount, on_date, member, title)
    transfer = None
    if source:
        reserve = reserve_account(household, currency)
        if taking:
            transfer = move(household, reserve, source, convert(amount, currency, source.currency, on_date), on_date, member, title)
        else:
            transfer = move(household, source, reserve, amount, on_date, member, title)
    return GoalContribution.objects.create(
        goal=goal, date=on_date, amount=-amount if taking else amount, member=member, note=note,
        transaction=transfer, currency="" if currency == household.base_currency else currency,
    )


@db_transaction.atomic
def remove_contribution(contribution):
    if contribution.transaction_id:
        contribution.transaction.delete()
    else:
        contribution.delete()


def moved_to_savings(household, start, end, member=None):
    transfers = household.transactions.filter(type=Transaction.Type.TRANSFER, date__gte=start, date__lte=end)
    if member:
        transfers = transfers.filter(member=member)
    saved = transfers.filter(account__kind__in=LIVE).exclude(to_account__kind__in=LIVE).total_base()
    taken = transfers.exclude(account__kind__in=LIVE).filter(to_account__kind__in=LIVE).total_base()
    return saved - taken


def typical_month(household, period):
    months = []
    for offset in range(1, TYPICAL_MONTHS + 1):
        past = period.shift(-offset)
        income_start, income_end = past.income_range()
        earned = household.transactions.incomes().between(income_start, income_end).total_base()
        spent = household.transactions.expenses().between(past.start, past.end).total_base()
        if earned or spent:
            months.append((earned, spent))
    if not months:
        return None, None
    income = sum((earned for earned, _spent in months), ZERO) / len(months)
    left = sum((earned - spent for earned, spent in months), ZERO) / len(months)
    return income, left


def goal_saved_in(household, period, today):
    total = ZERO
    contributions = GoalContribution.objects.filter(
        goal__household=household, date__gte=period.start, date__lte=period.end
    ).select_related("goal__account", "goal__household")
    for contribution in contributions:
        total += convert(contribution.amount, contribution.in_currency, household.base_currency, today)
    goal_accounts = household.goals.filter(is_archived=False, account__isnull=False).values_list("account", flat=True)
    transfers = household.transactions.filter(
        type=Transaction.Type.TRANSFER, date__gte=period.start, date__lte=period.end, account__kind__in=LIVE
    )
    total += transfers.filter(to_account__in=goal_accounts).total_base()
    return total


def month_plan(household, today, items=None):
    period = household.period(today)
    items = goal_items(household, today) if items is None else items
    base = household.base_currency
    plan = ZERO
    for item in items:
        plan += convert(item["plan"], item["goal"].currency, base, today)
    done = goal_saved_in(household, period, today)
    income, typical = typical_month(household, period)
    return {
        "period": period,
        "plan": plan,
        "done": done,
        "left": max(ZERO, plan - done),
        "percent": min(100, round(done / plan * 100)) if plan else 0,
        "typical": typical,
        "too_much": typical is not None and plan > max(typical, ZERO),
        "suggested": (income * Decimal("0.1")).quantize(Decimal("1")) if income else None,
    }
