import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.goals.models import Goal, GoalContribution
from apps.goals.services import goal_items
from apps.households.services import create_household
from apps.money.models import Account, Transaction

TODAY = datetime.date(2026, 10, 23)


@pytest.fixture
def yura_client(client, yura):
    client.force_login(yura.user)
    return client


@pytest.fixture
def jar(home):
    return Account.objects.create(household=home, name="Банка", kind=Account.Kind.SAVINGS, opening_balance=Decimal("5000"))


def test_account_goal_counts_account_balance(home, mono, jar):
    goal = Goal.objects.create(household=home, name="Ремонт", target_amount=Decimal("20000"), account=jar)
    GoalContribution.objects.create(goal=goal, amount=Decimal("99999"))
    Transaction.objects.create(
        household=home, type="transfer", account=mono, to_account=jar, amount=Decimal("3000"), title="x", date=TODAY,
    )

    item = goal_items(home, TODAY)[0]

    assert item["saved"] == Decimal("8000")
    assert item["progress"] == 40


def test_manual_goal_counts_contributions_with_withdrawals(home):
    goal = Goal.objects.create(household=home, name="Подарунок", target_amount=Decimal("1000"))
    GoalContribution.objects.create(goal=goal, amount=Decimal("1200"))
    GoalContribution.objects.create(goal=goal, amount=Decimal("-300"))

    item = goal_items(home, TODAY)[0]

    assert item["saved"] == Decimal("900")
    assert not item["done"]


def test_done_and_overdue_flags(home):
    Goal.objects.create(household=home, name="Стара", target_amount=Decimal("100"), deadline=datetime.date(2026, 1, 1))
    done = Goal.objects.create(household=home, name="Готова", target_amount=Decimal("100"))
    GoalContribution.objects.create(goal=done, amount=Decimal("150"))

    items = {item["goal"].name: item for item in goal_items(home, TODAY)}

    assert items["Стара"]["overdue"]
    assert items["Готова"]["done"]
    assert items["Готова"]["progress"] == 100


def test_create_manual_goal(yura_client, home):
    yura_client.post(reverse("goals:goal_create"), {
        "mode": "manual", "name": " Відпустка ", "target_amount": "60 000", "deadline": "2027-06-01",
        "account": "", "color_slot": "3", "icon": "beach", "emoji": "",
    })

    goal = home.goals.get()
    assert (goal.name, goal.target_amount, goal.account, goal.icon, goal.color_slot) == (
        "Відпустка", Decimal("60000"), None, "beach", 3,
    )


def test_create_account_goal_needs_account(yura_client, home, jar):
    response = yura_client.post(reverse("goals:goal_create"), {"mode": "account", "name": "Ремонт", "target_amount": "20000"})
    assert "account" in response.context["form"].errors

    yura_client.post(reverse("goals:goal_create"), {"mode": "account", "name": "Ремонт", "target_amount": "20000", "account": jar.pk})
    assert home.goals.get().account == jar


def test_account_can_track_only_one_active_goal(yura_client, home, jar):
    Goal.objects.create(household=home, name="Перша", target_amount=Decimal("100"), account=jar)

    response = yura_client.post(reverse("goals:goal_create"), {"mode": "account", "name": "Друга", "target_amount": "100", "account": jar.pk})

    assert "account" in response.context["form"].errors


def test_switch_to_manual_drops_account(yura_client, home, jar):
    goal = Goal.objects.create(household=home, name="Ремонт", target_amount=Decimal("100"), account=jar)

    yura_client.post(reverse("goals:goal_edit", args=[goal.pk]), {
        "mode": "manual", "name": "Ремонт", "target_amount": "100", "account": jar.pk, "color_slot": "1",
    })

    goal.refresh_from_db()
    assert goal.account is None


def test_contribution_in_and_out(yura_client, home, yura):
    goal = Goal.objects.create(household=home, name="Подарунок", target_amount=Decimal("1000"))
    url = reverse("goals:contribution_create", args=[goal.pk])

    yura_client.post(url, {"direction": "in", "amount": "500", "date": "2026-10-23", "member": yura.pk})
    yura_client.post(url, {"direction": "out", "amount": "120,50", "date": "2026-10-23", "member": ""})

    assert sorted(goal.contributions.values_list("amount", flat=True)) == [Decimal("-120.50"), Decimal("500")]


def test_no_manual_contributions_for_account_goal(yura_client, home, jar):
    goal = Goal.objects.create(household=home, name="Ремонт", target_amount=Decimal("100"), account=jar)

    assert yura_client.get(reverse("goals:contribution_create", args=[goal.pk])).status_code == 404


def test_archive_and_delete(yura_client, home):
    goal = Goal.objects.create(household=home, name="Ціль", target_amount=Decimal("100"))

    yura_client.post(reverse("goals:goal_archive", args=[goal.pk]))
    goal.refresh_from_db()
    assert goal.is_archived
    assert yura_client.get(reverse("goals:goals")).context["archived_count"] == 1

    yura_client.post(reverse("goals:goal_delete", args=[goal.pk]))
    assert not home.goals.exists()


def test_page_totals(yura_client, home):
    goal = Goal.objects.create(household=home, name="Ціль", target_amount=Decimal("1000"))
    GoalContribution.objects.create(goal=goal, amount=Decimal("250"))

    response = yura_client.get(reverse("goals:goals"))

    assert (response.context["saved"], response.context["target"]) == (Decimal("250"), Decimal("1000"))


def test_foreign_goal_is_hidden(yura_client, user):
    stranger = create_household(user, "Чужий дім")
    goal = Goal.objects.create(household=stranger, name="Чужа", target_amount=Decimal("100"))

    assert yura_client.get(reverse("goals:goal_edit", args=[goal.pk])).status_code == 404
    assert yura_client.post(reverse("goals:goal_delete", args=[goal.pk])).status_code == 404
    assert yura_client.get(reverse("goals:contribution_create", args=[goal.pk])).status_code == 404


def test_transfer_form_prefills_target_account(yura_client, jar):
    response = yura_client.get(reverse("money:transaction_create"), {"type": "transfer", "to_account": jar.pk})

    assert str(response.context["form"]["to_account"].value()) == str(jar.pk)
