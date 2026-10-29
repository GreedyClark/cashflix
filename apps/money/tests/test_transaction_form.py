import datetime
import json
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.households.services import create_household
from apps.money.models import Transaction


@pytest.fixture
def yura_client(client, yura):
    client.force_login(yura.user)
    return client


@pytest.fixture
def silpo(home, mono, food, olya):
    return Transaction.objects.create(
        household=home, account=mono, category=food, member=olya, amount=Decimal("486"),
        title="Сільпо", date=datetime.date(2026, 10, 14),
    )


def payload(**fields):
    data = {
        "type": "expense", "amount": "486,50", "title": "Сільпо", "when": "other", "date": "2026-10-14",
        "member": "", "note": "",
    }
    data.update(fields)
    return data


def test_new_form_suggests_my_account_and_me(yura_client, mono, yura):
    response = yura_client.get(reverse("money:transaction_create"))
    form = response.context["form"]

    assert response.status_code == 200
    assert form.initial["member"] == yura
    assert form.initial["account"] == mono


def test_create_expense_with_comma_amount(yura_client, home, mono, food, yura):
    response = yura_client.post(
        reverse("money:transaction_create"), payload(account=mono.pk, category=food.pk, member=yura.pk)
    )

    assert response.status_code == 200
    assert json.loads(response["HX-Trigger"])["transactionsChanged"]
    assert "Операцію додано" in response.content.decode()
    tx = home.transactions.get()
    assert tx.amount == Decimal("486.50")
    assert tx.member == yura
    assert tx.created_by == yura.user


def test_errors_are_shown_in_form(yura_client, home, mono):
    response = yura_client.post(reverse("money:transaction_create"), payload(account=mono.pk, amount="0", title=""))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Вкажіть суму більше нуля." in html
    assert "Вкажіть назву" in html
    assert not home.transactions.exists()


def test_transfer_ignores_category(yura_client, home, mono, cash, food):
    yura_client.post(
        reverse("money:transaction_create"),
        payload(type="transfer", account=mono.pk, to_account=cash.pk, category=food.pk, title="Готівка"),
    )

    tx = home.transactions.get()
    assert tx.is_transfer
    assert tx.category is None
    assert tx.to_account == cash


def test_edit_changes_amount_and_category(yura_client, silpo, home_subs):
    response = yura_client.post(
        reverse("money:transaction_edit", args=[silpo.pk]),
        payload(account=silpo.account_id, category=home_subs.pk, amount="500"),
    )

    assert response["HX-Reswap"] == "none"
    silpo.refresh_from_db()
    assert silpo.amount == Decimal("500")
    assert silpo.amount_base == Decimal("500")
    assert silpo.category == home_subs


def test_delete_and_undo(yura_client, home, silpo):
    response = yura_client.post(reverse("money:transaction_delete", args=[silpo.pk]))

    assert reverse("money:transaction_undo") in response.content.decode()
    assert not home.transactions.exists()

    yura_client.post(reverse("money:transaction_undo"))

    restored = home.transactions.get()
    assert restored.pk == silpo.pk
    assert restored.amount == Decimal("486")
    assert restored.member == silpo.member
    assert restored.created_at == silpo.created_at


def test_other_family_cannot_open_or_delete(client, silpo, user):
    create_household(user, "Чужий дім")
    client.force_login(user)

    assert client.get(reverse("money:transaction_edit", args=[silpo.pk])).status_code == 404
    assert client.post(reverse("money:transaction_delete", args=[silpo.pk])).status_code == 404
    assert Transaction.objects.filter(pk=silpo.pk).exists()


def test_cannot_use_category_of_other_family(yura_client, home, mono, user):
    stranger = create_household(user, "Чужий дім")
    foreign = stranger.categories.get(name="Продукти")

    response = yura_client.post(reverse("money:transaction_create"), payload(account=mono.pk, category=foreign.pk))

    assert response.status_code == 200
    assert not home.transactions.exists()


def test_today_and_yesterday_shortcuts(yura_client, home, mono, food):
    yura_client.post(reverse("money:transaction_create"), payload(account=mono.pk, category=food.pk, when="yesterday"))

    assert home.transactions.get().date == timezone.localdate() - datetime.timedelta(days=1)


def test_category_of_other_type_is_rejected(yura_client, home, mono, salary):
    response = yura_client.post(reverse("money:transaction_create"), payload(account=mono.pk, category=salary.pk))

    assert "Оберіть категорію." in response.content.decode()
    assert not home.transactions.exists()


def test_income_without_title_uses_category(yura_client, home, mono, salary, yura):
    yura_client.post(
        reverse("money:transaction_create"),
        payload(type="income", account=mono.pk, category=salary.pk, member=yura.pk, title="", amount="30000"),
    )

    assert home.transactions.get().title == "Зарплата"


def test_income_without_title_and_category_asks_for_one(yura_client, home, mono):
    response = yura_client.post(reverse("money:transaction_create"), payload(type="income", account=mono.pk, title=""))

    assert "Оберіть категорію або вкажіть назву." in response.content.decode()
    assert not home.transactions.exists()


def test_refund_checkbox_stores_negative_expense(yura_client, home, mono, food):
    yura_client.post(reverse("money:transaction_create"), payload(account=mono.pk, category=food.pk, amount="200", is_refund="on"))

    tx = home.transactions.get()
    assert (tx.amount, tx.is_refund) == (Decimal("-200.00"), True)
    mono.refresh_from_db()
    assert mono.get_balance() == Decimal("1200.00")


def test_converting_to_transfer_absorbs_other_half(yura_client, home, mono, cash, food):
    gifts = home.categories.get(kind="income", name="Подарунки")
    out = Transaction.objects.create(household=home, account=mono, category=food, amount=Decimal("500"), title="Переказ на картку", date=datetime.date(2026, 10, 14))
    Transaction.objects.create(household=home, account=cash, category=gifts, type="income", amount=Decimal("500"), title="Переказ з картки", date=datetime.date(2026, 10, 14))

    yura_client.post(reverse("money:transaction_edit", args=[out.pk]), payload(type="transfer", account=mono.pk, to_account=cash.pk, title="Переказ на картку", amount="500"))

    tx = home.transactions.get()
    assert (tx.type, tx.to_account) == ("transfer", cash)
