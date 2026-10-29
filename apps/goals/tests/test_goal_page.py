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


def test_account_goal_contribution_is_transfer(yura_client, home, mono, jar):
    goal = Goal.objects.create(household=home, name="Ремонт", target_amount=Decimal("100000"), account=jar)

    yura_client.post(reverse("goals:contribution_create", args=[goal.pk]), {"direction": "in", "amount": "2000", "date": "2026-10-25", "source": mono.pk, "member": ""})

    tx = home.transactions.get()
    assert (tx.type, tx.account, tx.to_account, tx.amount) == ("transfer", mono, jar, Decimal("2000"))
    assert jar.get_balance() == Decimal("7000")
    assert not goal.contributions.exists()


def test_manual_goal_from_card_moves_money_to_reserve(yura_client, home, mono):
    goal = Goal.objects.create(household=home, name="Відпустка", target_amount=Decimal("60000"))

    yura_client.post(reverse("goals:contribution_create", args=[goal.pk]), {"direction": "in", "amount": "3000", "date": "2026-10-25", "source": mono.pk, "member": ""})

    contribution = goal.contributions.get()
    reserve = contribution.transaction.to_account
    assert (reserve.kind, reserve.name) == ("savings", "Відкладено на цілі")
    assert mono.get_balance() == Decimal("-2000")
    assert reserve.get_balance() == Decimal("3000")
    assert goal.get_saved() == Decimal("3000")


def test_manual_goal_without_card_only_records(yura_client, home, mono):
    goal = Goal.objects.create(household=home, name="Подарунок", target_amount=Decimal("1000"))

    yura_client.post(reverse("goals:contribution_create", args=[goal.pk]), {"direction": "in", "amount": "300", "date": "2026-10-25", "source": "", "member": ""})

    assert goal.get_saved() == Decimal("300")
    assert not home.transactions.exists()


def test_dollar_goal_from_hryvnia_card(yura_client, home, mono, usd_rate):
    goal = Goal.objects.create(household=home, name="Подушка", target_amount=Decimal("5000"), currency_code="USD")

    yura_client.post(reverse("goals:contribution_create", args=[goal.pk]), {"direction": "in", "amount": "100", "date": "2026-10-25", "source": mono.pk, "member": ""})

    transfer = goal.contributions.get().transaction
    assert (transfer.amount, transfer.to_amount, transfer.to_account.currency) == (Decimal("4132.00"), Decimal("100"), "USD")
    assert transfer.to_account.name == "Відкладено на цілі USD"


def test_month_plan_and_reality_check(home, mono, food, salary):
    from apps.goals.services import month_plan

    today = datetime.date(2026, 10, 25)
    Goal.objects.create(household=home, name="Ноутбук", target_amount=Decimal("30000"), deadline=datetime.date(2027, 4, 25))
    Goal.objects.create(household=home, name="Подушка", target_amount=Decimal("100000"), monthly_amount=Decimal("3000"))
    for month in (7, 8, 9):
        Transaction.objects.create(household=home, account=mono, category=salary, type="income", amount=Decimal("20000"), date=datetime.date(2026, month, 5), title="ЗП")
        Transaction.objects.create(household=home, account=mono, category=food, amount=Decimal("15000"), date=datetime.date(2026, month, 10), title="x")

    plan = month_plan(home, today)

    assert plan["plan"] == Decimal("8000")
    assert plan["typical"] == Decimal("5000")
    assert plan["too_much"]


def test_goal_in_dollars_saved_from_form(yura_client, home):
    yura_client.post(reverse("goals:goal_create"), {"mode": "manual", "name": "Подушка", "target_amount": "5000", "currency_code": "USD", "monthly_amount": "200"})

    goal = Goal.objects.get()
    assert (goal.currency, goal.monthly_amount) == ("USD", Decimal("200"))

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


def test_old_hryvnia_contributions_convert_after_currency_change(home, usd_rate):
    goal = Goal.objects.create(household=home, name="Подушка", target_amount=Decimal("6000"))
    GoalContribution.objects.create(goal=goal, amount=Decimal("41320"), date=datetime.date(2026, 10, 5))
    goal.currency_code = "USD"
    goal.save()

    item = goal_items(home, TODAY)[0]

    assert item["saved"] == Decimal("1000.00")
    assert goal.get_saved() == Decimal("1000.00")


def test_dollar_contribution_remembers_its_currency(yura_client, home, usd_rate):
    goal = Goal.objects.create(household=home, name="Подушка", target_amount=Decimal("5000"), currency_code="USD")

    yura_client.post(reverse("goals:contribution_create", args=[goal.pk]), {"direction": "in", "amount": "100", "date": "2026-10-25", "source": "", "member": ""})

    assert goal.contributions.get().currency == "USD"
    assert goal.get_saved() == Decimal("100")


def test_edit_contribution_updates_its_transfer(yura_client, home, mono):
    goal = Goal.objects.create(household=home, name="Відпустка", target_amount=Decimal("60000"))
    yura_client.post(reverse("goals:contribution_create", args=[goal.pk]), {"direction": "in", "amount": "3000", "date": "2026-10-25", "source": mono.pk, "member": ""})
    contribution = goal.contributions.get()

    form = yura_client.get(reverse("goals:contribution_edit", args=[contribution.pk]))
    assert 'value="3000"' in form.content.decode()

    yura_client.post(reverse("goals:contribution_edit", args=[contribution.pk]), {"direction": "in", "amount": "2500", "date": "2026-10-26", "source": mono.pk, "member": "", "note": "Премія"})

    contribution = goal.contributions.get()
    assert (contribution.amount, contribution.date, contribution.note) == (Decimal("2500"), datetime.date(2026, 10, 26), "Премія")
    assert home.transactions.get().amount == Decimal("2500")
    assert mono.get_balance() == Decimal("-1500")


def test_edit_keeps_hryvnia_contribution_in_hryvnia(yura_client, home, usd_rate):
    goal = Goal.objects.create(household=home, name="Подушка", target_amount=Decimal("6000"), currency_code="USD")
    contribution = GoalContribution.objects.create(goal=goal, amount=Decimal("41320"), date=datetime.date(2026, 10, 5))

    yura_client.post(reverse("goals:contribution_edit", args=[contribution.pk]), {"direction": "in", "amount": "82640", "date": "2026-10-05", "source": "", "member": ""})

    contribution = goal.contributions.get()
    assert (contribution.amount, contribution.in_currency) == (Decimal("82640"), "UAH")
    assert goal.get_saved() == Decimal("2000.00")


def test_delete_contribution_removes_transfer(yura_client, home, mono):
    goal = Goal.objects.create(household=home, name="Відпустка", target_amount=Decimal("60000"))
    yura_client.post(reverse("goals:contribution_create", args=[goal.pk]), {"direction": "in", "amount": "3000", "date": "2026-10-25", "source": mono.pk, "member": ""})

    yura_client.post(reverse("goals:contribution_delete", args=[goal.contributions.get().pk]))

    assert not goal.contributions.exists()
    assert not home.transactions.exists()
    assert mono.get_balance() == Decimal("1000")


def test_cannot_edit_contribution_of_other_family(yura_client, user):
    stranger = create_household(user, "Чужий дім")
    goal = Goal.objects.create(household=stranger, name="Чужа", target_amount=Decimal("100"))
    contribution = GoalContribution.objects.create(goal=goal, amount=Decimal("10"))

    assert yura_client.get(reverse("goals:contribution_edit", args=[contribution.pk])).status_code == 404
    assert yura_client.post(reverse("goals:contribution_delete", args=[contribution.pk])).status_code == 404
    assert GoalContribution.objects.filter(pk=contribution.pk).exists()
