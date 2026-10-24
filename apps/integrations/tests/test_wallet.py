import json
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.integrations.models import ShortcutToken, WalletCard
from apps.integrations.wallet import card_key, currency_of
from apps.money.models import Account


@pytest.fixture
def raw_token(yura):
    _token, raw = ShortcutToken.issue(yura)
    return raw


def pay(client, token, **payload):
    return client.post(
        reverse("integrations:shortcut_api"), json.dumps(payload), content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_card_key_understands_latin_bank_names():
    assert card_key("Monobank  Black") == "монобанк black"
    assert card_key("PrivatBank Універсальна") == "приватбанк універсальна"


def test_currency_from_amount(home):
    assert currency_of("$12.50", home) == "USD"
    assert currency_of("12,50 €", home) == "EUR"
    assert currency_of("486 ₴", home) == "UAH"


def test_new_card_becomes_account_and_is_reused(client, home, yura, mono, raw_token):
    pay(client, raw_token, amount="439", merchant="Сільпо", card="Універсальна")
    pay(client, raw_token, amount="120", merchant="АТБ", card="Універсальна")

    account = home.accounts.get(name="Універсальна")
    assert (account.kind, account.owner, account.currency) == (Account.Kind.CARD, yura, "UAH")
    assert account.transactions.count() == 2
    assert WalletCard.objects.get().auto_created


def test_card_matching_existing_account_is_remembered(client, home, mono, raw_token):
    pay(client, raw_token, amount="50", merchant="АТБ", card="Monobank Black")

    card = WalletCard.objects.get()
    assert (card.account, card.auto_created) == (mono, False)


def test_dollar_card_gets_dollar_account(client, home, mono, raw_token):
    pay(client, raw_token, amount="$20", merchant="Steam", card="Revolut")

    assert home.accounts.get(name="Revolut").currency == "USD"


def test_relink_moves_payments_and_removes_empty_auto_account(client, home, yura, mono, raw_token):
    pay(client, raw_token, amount="439", merchant="Сільпо", card="Універсальна")
    card = WalletCard.objects.get()
    client.force_login(yura.user)

    client.post(reverse("integrations:wallet_links"), {f"card_{card.pk}": mono.pk})

    card.refresh_from_db()
    assert card.account == mono
    assert mono.transactions.get().amount == Decimal("439.00")
    assert not home.accounts.filter(name="Універсальна").exists()


def test_ignored_card_is_skipped(client, home, yura, mono, raw_token):
    pay(client, raw_token, amount="10", merchant="x", card="Ощад")
    card = WalletCard.objects.get()
    client.force_login(yura.user)
    client.post(reverse("integrations:wallet_links"), {f"card_{card.pk}": ""})

    response = pay(client, raw_token, amount="15", merchant="y", card="Ощад")

    assert response.json()["status"] == "skipped"
    assert home.transactions.count() == 1


def test_connections_page_lists_wallet_cards(client, yura, mono, raw_token):
    pay(client, raw_token, amount="10", merchant="x", card="Універсальна")
    client.force_login(yura.user)

    response = client.get(reverse("integrations:connections"))

    assert "Картки з Гаманця" in response.content.decode()
