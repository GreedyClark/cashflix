import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.budgets.models import Limit
from apps.budgets.periods import Period
from apps.budgets.summary import BudgetMonth, SpendingHistory
from apps.households.services import create_household
from apps.money.icon_catalog import search, suggest
from apps.money.models import Category, Transaction

MONTH = Period.containing(datetime.date(2026, 10, 1))
TODAY = datetime.date(2026, 10, 22)


@pytest.fixture
def yura_client(client, yura):
    client.force_login(yura.user)
    return client


def spend(home, mono, category, amount, date, member=None):
    Transaction.objects.create(
        household=home, account=mono, category=category, member=member, amount=Decimal(amount), date=date, title="x"
    )


def test_summary_and_states(home, mono, food, home_subs):
    Limit.objects.create(household=home, category=food, amount=Decimal("1000"))
    Limit.objects.create(household=home, category=home_subs, amount=Decimal("500"))
    spend(home, mono, food, "1200", datetime.date(2026, 10, 5))
    spend(home, mono, home_subs, "420", datetime.date(2026, 10, 6))

    budget = BudgetMonth(home, MONTH, TODAY)
    limits = budget.limits()
    summary = budget.summary(limits)

    assert {item["limit"].category: item["state"] for item in limits} == {food: "crit", home_subs: "warn"}
    assert summary["planned"] == Decimal("1500")
    assert summary["spent"] == Decimal("1620")
    assert summary["left"] == Decimal("-120")
    assert summary["per_day"] is None
    assert summary["over"] == [food.name]
    assert summary["pace"] == 71


def test_average_uses_three_previous_months(home, mono, food, olya):
    spend(home, mono, food, "3000", datetime.date(2026, 7, 10), olya)
    spend(home, mono, food, "3000", datetime.date(2026, 9, 10))
    spend(home, mono, food, "9999", datetime.date(2026, 10, 3))
    spend(home, mono, food, "9999", datetime.date(2026, 6, 30))

    history = SpendingHistory(home, MONTH)

    assert history.for_limit(food.pk).average == Decimal("2000")
    assert history.for_limit(food.pk).previous == Decimal("3000")
    assert history.for_limit(food.pk, olya.pk).average == Decimal("1000")


def test_free_categories_exclude_limited(home, food, home_subs):
    Limit.objects.create(household=home, category=food, amount=Decimal("1000"))

    budget = BudgetMonth(home, MONTH, TODAY)
    free = [item["category"] for item in budget.free_categories(budget.limits())]

    assert food not in free
    assert home_subs in free


def test_page_renders(yura_client, home, food):
    Limit.objects.create(household=home, category=food, amount=Decimal("1000"))

    response = yura_client.get(reverse("budgets:budget"))

    assert response.status_code == 200
    assert len(response.context["limits"]) == 1


def test_create_limit_for_existing_category(yura_client, home, food):
    response = yura_client.post(reverse("budgets:limit_create"), {"category": food.pk, "amount": "2 500", "member": ""})

    assert response["HX-Reswap"] == "none"
    assert Limit.objects.get(household=home).amount == Decimal("2500")


def test_duplicate_limit_is_rejected(yura_client, home, food):
    Limit.objects.create(household=home, category=food, amount=Decimal("1000"))

    response = yura_client.post(reverse("budgets:limit_create"), {"category": food.pk, "amount": "500", "member": ""})

    assert response.context["form"].non_field_errors()
    assert Limit.objects.count() == 1


def test_personal_and_shared_limits_can_coexist(yura_client, home, food, olya):
    Limit.objects.create(household=home, category=food, amount=Decimal("1000"))

    yura_client.post(reverse("budgets:limit_create"), {"category": food.pk, "amount": "500", "member": olya.pk})

    assert Limit.objects.filter(category=food).count() == 2


def test_create_limit_with_new_category(yura_client, home):
    yura_client.post(reverse("budgets:limit_create"), {
        "category": "new", "name": "  Тварини ", "color_slot": "3", "icon": "paw", "amount": "1500", "member": "",
    })

    category = home.categories.get(name="Тварини")
    assert category.kind == Category.Kind.EXPENSE
    assert (category.icon, category.color_slot, category.emoji) == ("paw", 3, "")
    assert Limit.objects.get(category=category).amount == Decimal("1500")


def test_new_category_with_emoji_and_unknown_icon(yura_client, home):
    yura_client.post(reverse("budgets:limit_create"), {
        "category": "new", "name": "Риболовля", "icon": "rocket-launcher", "emoji": "🎣", "amount": "800",
    })

    category = home.categories.get(name="Риболовля")
    assert category.icon == ""
    assert category.emoji == "🎣"


def test_new_category_name_must_be_unique(yura_client, home, food):
    response = yura_client.post(reverse("budgets:limit_create"), {
        "category": "new", "name": food.name.upper(), "amount": "800",
    })

    assert "name" in response.context["category_form"].errors
    assert not Limit.objects.exists()


def test_emoji_field_rejects_text(yura_client, home):
    response = yura_client.post(reverse("budgets:limit_create"), {
        "category": "new", "name": "Хобі", "emoji": "abc", "amount": "800",
    })

    assert "emoji" in response.context["category_form"].errors


def test_edit_keeps_category_and_delete(yura_client, home, food, home_subs):
    limit = Limit.objects.create(household=home, category=food, amount=Decimal("1000"))

    yura_client.post(reverse("budgets:limit_edit", args=[limit.pk]), {"category": home_subs.pk, "amount": "1 200", "member": ""})
    limit.refresh_from_db()
    assert (limit.category, limit.amount) == (food, Decimal("1200"))

    yura_client.post(reverse("budgets:limit_delete", args=[limit.pk]))
    assert not Limit.objects.exists()


def test_foreign_limit_is_hidden(yura_client, user):
    stranger = create_household(user, "Чужий дім")
    category = stranger.categories.filter(kind="expense").first()
    limit = Limit.objects.create(household=stranger, category=category, amount=Decimal("100"))

    assert yura_client.get(reverse("budgets:limit_edit", args=[limit.pk])).status_code == 404
    assert yura_client.post(reverse("budgets:limit_delete", args=[limit.pk])).status_code == 404


def test_foreign_category_cannot_be_used(yura_client, home, user):
    stranger = create_household(user, "Чужий дім")
    category = stranger.categories.filter(kind="expense").first()

    response = yura_client.post(reverse("budgets:limit_create"), {"category": category.pk, "amount": "100"})

    assert "category" in response.context["form"].errors


def test_icon_suggest_and_search():
    assert suggest("Тварини") == "paw"
    assert suggest("Вʼязання") == "needle-thread"
    assert suggest("Абракадабра") == ""
    assert "barbell" in search("спорт")
    assert "car" not in search("спорт")


def test_icon_grid_suggests_by_name(yura_client):
    response = yura_client.get(reverse("money:icon_grid"), {"name": "Бензин", "trigger": "name", "icon": "cat"})

    assert response.context["icons"]["selected"] == "gas-station"


def test_icon_grid_keeps_picked_icon_while_searching(yura_client):
    response = yura_client.get(reverse("money:icon_grid"), {"name": "Бензин", "icon_query": "кіт", "icon": "cat"})

    assert response.context["icons"]["selected"] == "cat"
