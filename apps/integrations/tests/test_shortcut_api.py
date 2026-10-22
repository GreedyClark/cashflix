import json
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.integrations.models import ShortcutToken
from apps.integrations.parsing import BadPayload, parse_amount
from apps.households.services import remove_member
from apps.money.models import Account


@pytest.fixture
def raw_token(yura):
    _token, raw = ShortcutToken.issue(yura)
    return raw


def post(client, token, **payload):
    return client.post(
        reverse("integrations:shortcut_api"), json.dumps(payload), content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.parametrize("value, expected", [
    ("486", "486.00"), ("₴486,50", "486.50"), ("1 234,56 ₴", "1234.56"), ("$1,234.56", "1234.56"),
    ("-99.9", "99.90"), (120, "120.00"),
])
def test_parse_amount(value, expected):
    assert parse_amount(value) == Decimal(expected)


def test_parse_amount_rejects_garbage():
    with pytest.raises(BadPayload):
        parse_amount("абв")


def test_creates_categorized_expense(client, home, yura, mono, raw_token):
    response = post(client, raw_token, amount="₴486,00", merchant="SILPO 1234", card="Monobank Black", id="r1")

    assert response.status_code == 201
    data = response.json()
    assert (data["status"], data["category"], data["review"]) == ("created", "Продукти", False)
    tx = home.transactions.get()
    assert (tx.amount, tx.account, tx.member, tx.source, tx.external_id) == (Decimal("486.00"), mono, yura, "shortcut", "r1")
    assert tx.occurred_at is not None


def test_repeat_request_is_duplicate(client, home, raw_token, mono):
    post(client, raw_token, amount="50", merchant="АТБ", id="same")
    response = post(client, raw_token, amount="50", merchant="АТБ", id="same")

    assert response.json()["status"] == "duplicate"
    assert home.transactions.count() == 1


def test_card_name_picks_account(client, home, raw_token, mono, cash):
    post(client, raw_token, amount="20", merchant="Кіоск", card="Готівка")

    assert home.transactions.get().account == cash


def test_default_account_from_settings(client, home, yura, raw_token, mono, cash):
    token = ShortcutToken.objects.get(membership=yura)
    token.account = cash
    token.save()

    post(client, raw_token, amount="20", merchant="Кіоск", card="Невідома картка")

    assert home.transactions.get().account == cash


def test_bad_token_and_bad_amount(client, raw_token, mono):
    assert post(client, "nope", amount="10", merchant="x").status_code == 401
    response = post(client, raw_token, amount="", merchant="x")
    assert (response.status_code, response.json()["error"]) == (400, "amount")


def test_token_in_body_also_works(client, home, raw_token, mono):
    response = client.post(
        reverse("integrations:shortcut_api"), json.dumps({"token": raw_token, "amount": "10", "merchant": "x"}),
        content_type="application/json",
    )
    assert response.status_code == 201


def test_left_member_token_stops_working(client, home, olya, mono):
    _token, raw = ShortcutToken.issue(olya)
    remove_member(olya)

    assert post(client, raw, amount="10", merchant="x").status_code == 401


def test_connections_page_issue_and_revoke(client, yura):
    client.force_login(yura.user)

    response = client.post(reverse("integrations:token_issue"), follow=True)
    raw = response.context["raw_token"]
    assert raw.startswith("cf_")
    assert ShortcutToken.objects.find(raw).membership == yura
    assert client.get(reverse("integrations:connections")).context["raw_token"] is None

    client.post(reverse("integrations:token_revoke"))
    assert not ShortcutToken.objects.exists()


def test_new_token_replaces_old(client, yura, raw_token):
    _token, fresh = ShortcutToken.issue(yura)

    assert ShortcutToken.objects.find(raw_token) is None
    assert ShortcutToken.objects.find(fresh) is not None
