import datetime
from decimal import Decimal

from apps.goals.models import Goal, GoalContribution


def test_saved_and_progress(home):
    goal = Goal.objects.create(household=home, name="Відпустка", target_amount=Decimal("60000"))
    GoalContribution.objects.create(goal=goal, amount=Decimal("20000"))
    GoalContribution.objects.create(goal=goal, amount=Decimal("3400"))

    saved = Goal.objects.with_saved().get(pk=goal.pk).saved

    assert saved == Decimal("23400")
    assert goal.get_saved() == Decimal("23400")
    assert goal.progress(saved) == 39


def test_monthly_needed_splits_rest_until_deadline(home):
    goal = Goal.objects.create(
        household=home, name="Відпустка", target_amount=Decimal("60000"), deadline=datetime.date(2027, 6, 1)
    )

    needed = goal.monthly_needed(Decimal("23400"), today=datetime.date(2026, 10, 16))

    assert needed == Decimal("4575.00")


def test_monthly_needed_is_zero_when_goal_reached(home):
    goal = Goal.objects.create(
        household=home, name="Ноутбук", target_amount=Decimal("45000"), deadline=datetime.date(2026, 12, 1)
    )

    assert goal.monthly_needed(Decimal("45000")) == Decimal("0")
    assert goal.progress(Decimal("50000")) == 100