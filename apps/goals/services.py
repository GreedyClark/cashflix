from decimal import Decimal

from django.db.models import Max

from apps.money.accounts import load_accounts
from apps.money.models import Account

ZERO = Decimal("0")


def account_values(household, today, goals):
    linked = {goal.account_id for goal in goals if goal.account_id}
    if not linked:
        return {}
    values = {account.pk: account.value for account in load_accounts(household, today) if account.pk in linked}
    missing = linked - set(values)
    for account in Account.objects.with_balance().filter(pk__in=missing):
        values[account.pk] = account.balance
    return values


def goal_items(household, today, archived=False):
    goals = list(
        household.goals.filter(is_archived=archived)
        .select_related("account", "household")
        .with_saved()
        .annotate(last_date=Max("contributions__date"))
    )
    values = account_values(household, today, goals)
    items = []
    for goal in goals:
        saved = values.get(goal.account_id, ZERO) if goal.tracks_account else goal.saved
        items.append({
            "goal": goal,
            "saved": saved,
            "left": max(ZERO, goal.target_amount - saved),
            "progress": goal.progress(saved),
            "monthly": goal.monthly_needed(saved, today),
            "done": saved >= goal.target_amount,
            "overdue": bool(goal.deadline and goal.deadline < today and saved < goal.target_amount),
        })
    return items
