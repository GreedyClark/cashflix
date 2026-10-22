import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.budgets.models import Limit
from apps.households.services import create_household
from apps.money.models import Category, Transaction
from apps.recurring.models import RecurringPayment

DAY = datetime.date(2026, 10, 10)


@pytest.fixture
def yura_client(client, yura):
    client.force_login(yura.user)
    return client


@pytest.fixture
def cafe(home):
    return home.categories.get(kind=Category.Kind.EXPENSE, name="Кафе")


def spend(home, mono, category, amount="100", member=None):
    return Transaction.objects.create(
        household=home, account=mono, category=category, member=member, amount=Decimal(amount), date=DAY, title="x"
    )


def test_page_groups_categories_with_counts(yura_client, home, mono, food):
    spend(home, mono, food)
    spend(home, mono, food)

    response = yura_client.get(reverse("money:categories"))

    expenses, incomes = response.context["groups"]
    row = next(c for c in expenses["items"] if c == food)
    assert row.count == 2
    assert not row.can_delete
    assert all(c.kind == Category.Kind.INCOME for c in incomes["items"])


def test_create_income_category(yura_client, home):
    yura_client.post(reverse("money:category_create"), {"kind": "income", "name": "Фріланс", "icon": "briefcase", "color_slot": "2"})

    category = home.categories.get(name="Фріланс")
    assert (category.kind, category.icon, category.color_slot) == ("income", "briefcase", 2)


def test_same_name_allowed_in_other_kind_only(yura_client, home):
    response = yura_client.post(reverse("money:category_create"), {"kind": "expense", "name": "продукти"})
    assert "name" in response.context["form"].errors

    yura_client.post(reverse("money:category_create"), {"kind": "income", "name": "Продукти"})
    assert home.categories.filter(name="Продукти").count() == 2


def test_edit_keeps_kind_and_unknown_old_icon(yura_client, food):
    yura_client.post(reverse("money:category_edit", args=[food.pk]), {
        "kind": "income", "name": "Їжа", "icon": "shopping-cart", "color_slot": "5", "emoji": "",
    })

    food.refresh_from_db()
    assert (food.name, food.kind, food.color_slot) == ("Їжа", "expense", 5)


def test_rename_to_existing_name_is_rejected(yura_client, food, cafe):
    response = yura_client.post(reverse("money:category_edit", args=[food.pk]), {"name": "кафе", "color_slot": "1"})

    assert "name" in response.context["form"].errors


def test_archive_hides_from_transaction_form(yura_client, home, cafe):
    yura_client.post(reverse("money:category_archive", args=[cafe.pk]))
    cafe.refresh_from_db()
    assert cafe.is_archived

    response = yura_client.get(reverse("money:transaction_create"))
    assert cafe not in response.context["form"].fields["category"].queryset


def test_old_transaction_keeps_archived_category(yura_client, home, mono, cafe, yura):
    tx = spend(home, mono, cafe, member=yura)
    cafe.is_archived = True
    cafe.save()

    response = yura_client.get(reverse("money:transaction_edit", args=[tx.pk]))

    assert cafe in response.context["form"].fields["category"].queryset


def test_delete_only_empty_category(yura_client, home, mono, food, cafe):
    spend(home, mono, food)

    yura_client.post(reverse("money:category_delete", args=[food.pk]))
    yura_client.post(reverse("money:category_delete", args=[cafe.pk]))

    assert home.categories.filter(pk=food.pk).exists()
    assert not home.categories.filter(pk=cafe.pk).exists()


def test_category_with_recurring_payment_is_not_deleted(yura_client, home, mono, home_subs):
    RecurringPayment.objects.create(
        household=home, title="Spotify", account=mono, category=home_subs, amount=Decimal("199"), start_date=DAY,
    )

    yura_client.post(reverse("money:category_delete", args=[home_subs.pk]))

    assert home.categories.filter(pk=home_subs.pk).exists()


def test_merge_moves_everything(yura_client, home, mono, food, cafe, olya):
    spend(home, mono, cafe)
    spend(home, mono, cafe)
    RecurringPayment.objects.create(
        household=home, title="Кава", account=mono, category=cafe, amount=Decimal("80"), start_date=DAY,
    )
    Limit.objects.create(household=home, category=cafe, amount=Decimal("3000"))
    Limit.objects.create(household=home, category=cafe, member=olya, amount=Decimal("500"))
    Limit.objects.create(household=home, category=food, amount=Decimal("10000"))

    yura_client.post(reverse("money:category_merge", args=[cafe.pk]), {"target": food.pk})

    assert not home.categories.filter(pk=cafe.pk).exists()
    assert food.transactions.count() == 2
    assert food.recurring_payments.count() == 1
    assert sorted(food.limits.values_list("amount", flat=True)) == [Decimal("500"), Decimal("10000")]


def test_merge_only_into_same_kind(yura_client, home, cafe, salary):
    response = yura_client.post(reverse("money:category_merge", args=[cafe.pk]), {"target": salary.pk})

    assert "target" in response.context["form"].errors
    assert home.categories.filter(pk=cafe.pk).exists()


def test_foreign_category_is_hidden(yura_client, user):
    stranger = create_household(user, "Чужий дім")
    category = stranger.categories.first()

    assert yura_client.get(reverse("money:category_edit", args=[category.pk])).status_code == 404
    assert yura_client.post(reverse("money:category_delete", args=[category.pk])).status_code == 404
    assert yura_client.get(reverse("money:category_merge", args=[category.pk])).status_code == 404
