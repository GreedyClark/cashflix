import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.integrations import monobank
from apps.integrations.models import MonobankAccount, MonobankConnection
from apps.integrations.sync import connect, sync_account
from apps.money.models import Account, Transaction

NOW = timezone.make_aware(datetime.datetime(2026, 10, 20, 12, 0))
INFO = {
    "name": "Юрій",
    "accounts": [
        {"id": "black", "currencyCode": 980, "type": "black", "maskedPan": ["537541******1234"]},
        {"id": "usd", "currencyCode": 840, "type": "black", "maskedPan": ["537541******9999"]},
        {"id": "weird", "currencyCode": 985, "type": "black", "maskedPan": []},
    ],
    "jars": [{"id": "jar1", "currencyCode": 980, "title": "Відпустка"}],
}


def item(item_id, amount, minutes=0, description="Сільпо", mcc=5411):
    moment = NOW - datetime.timedelta(hours=1) + datetime.timedelta(minutes=minutes)
    return {"id": item_id, "time": int(moment.timestamp()), "amount": amount, "description": description, "mcc": mcc}


@pytest.fixture
def bank(monkeypatch):
    statements = {}

    def fake(token, path):
        if token != "good":
            raise monobank.MonobankAuthError("token")
        if path == "/personal/client-info":
            return INFO
        account_id = path.split("/")[3]
        return statements.get(account_id, [])

    monkeypatch.setattr(monobank, "request", fake)
    return statements


@pytest.fixture
def connection(bank, yura):
    return connect(yura, "good")


def link(connection, mono_id, account):
    item = connection.accounts.get(mono_id=mono_id)
    item.account = account
    item.save()
    connection.last_request_at = None
    connection.save()
    return item


def test_connect_stores_encrypted_token_and_accounts(connection):
    assert connection.token == "good"
    assert "good" not in connection.token_encrypted
    titles = sorted(connection.accounts.values_list("title", flat=True))
    assert titles == ["Банка «Відпустка»", "Чорна ·· 1234 UAH", "Чорна ·· 9999 USD"]


def test_bad_token(bank, yura):
    with pytest.raises(monobank.MonobankAuthError):
        connect(yura, "bad")
    assert not MonobankConnection.objects.exists()


def test_sync_creates_categorized_transactions(home, mono, connection, bank):
    bank["black"] = [item("a1", -48650), item("a2", 3000000, description="Зарплата", mcc=4829)]
    card = link(connection, "black", mono)

    results = sync_account(card, NOW)

    assert results["created"] == 2
    expense = home.transactions.get(external_id="a1")
    assert (expense.amount, expense.type, expense.category.name, expense.source) == (Decimal("486.50"), "expense", "Продукти", "monobank")
    assert home.transactions.get(external_id="a2").type == "income"
    card.refresh_from_db()
    assert card.synced_until == NOW


def test_mcc_used_when_name_unknown(home, mono, connection, bank):
    bank["black"] = [item("a1", -25000, description="ТОВ Ромашка", mcc=5812)]
    card = link(connection, "black", mono)

    sync_account(card, NOW)

    tx = home.transactions.get()
    assert (tx.category.name, tx.needs_review) == ("Кафе", False)


def test_second_sync_skips_known(home, mono, connection, bank):
    bank["black"] = [item("a1", -10000)]
    card = link(connection, "black", mono)
    sync_account(card, NOW)
    connection.last_request_at = None
    connection.save()

    results = sync_account(card, NOW + datetime.timedelta(minutes=5))

    assert results["duplicate"] == 1
    assert home.transactions.count() == 1


def test_rate_limit_is_respected(mono, connection, bank):
    card = link(connection, "black", mono)
    sync_account(card, NOW)

    with pytest.raises(monobank.MonobankRateLimit):
        sync_account(card, NOW + datetime.timedelta(seconds=20))


def test_shortcut_twin_is_merged(home, mono, connection, bank, yura):
    shortcut = Transaction.objects.create(
        household=home, account=mono, amount=Decimal("486.50"), title="SILPO", source="shortcut",
        category=home.categories.get(name="Продукти", kind="expense"), occurred_at=NOW - datetime.timedelta(minutes=58),
        date=NOW.date(), member=yura,
    )
    bank["black"] = [item("a1", -48650)]
    card = link(connection, "black", mono)

    results = sync_account(card, NOW)

    assert results["merged"] == 1
    assert list(home.transactions.all()) == [shortcut]


def test_own_transfer_becomes_transfer(home, mono, connection, bank):
    jar_account = Account.objects.create(household=home, name="Відпустка", kind=Account.Kind.SAVINGS)
    bank["black"] = [item("out", -200000, description="На банку «Відпустка»")]
    bank["jar1"] = [item("in", 200000, minutes=1, description="З чорної картки")]
    card = link(connection, "black", mono)
    jar = link(connection, "jar1", jar_account)

    sync_account(card, NOW)
    connection.last_request_at = None
    connection.save()
    results = sync_account(jar, NOW)

    assert results["transfer"] == 1
    tx = home.transactions.get()
    assert (tx.type, tx.account, tx.to_account, tx.category) == ("transfer", mono, jar_account, None)


def test_shortcut_skips_monobank_account(client, home, yura, mono, connection):
    from apps.integrations.models import ShortcutToken
    import json

    link(connection, "black", mono)
    _token, raw = ShortcutToken.issue(yura)

    response = client.post(
        reverse("integrations:shortcut_api"), json.dumps({"amount": "10", "merchant": "x", "card": "Монобанк"}),
        content_type="application/json", headers={"Authorization": f"Bearer {raw}"},
    )

    assert response.json()["status"] == "skipped"
    assert not home.transactions.exists()


def test_page_connect_link_and_sync(client, home, yura, mono, usd_account, bank):
    client.force_login(yura.user)
    bank["black"] = [item("a1", -10000, minutes=50)]

    client.post(reverse("integrations:monobank_connect"), {"mono_token": "good"})
    connection = MonobankConnection.objects.get(membership=yura)
    black = connection.accounts.get(mono_id="black")
    usd = connection.accounts.get(mono_id="usd")
    client.post(reverse("integrations:monobank_links"), {f"link_{black.pk}": mono.pk, f"link_{usd.pk}": mono.pk})
    black.refresh_from_db()
    usd.refresh_from_db()
    assert (black.account, usd.account) == (mono, None)

    connection.last_request_at = None
    connection.save()
    response = client.post(reverse("integrations:monobank_sync", args=[black.pk]), follow=True)

    assert "нових 1" in response.content.decode()
    assert home.transactions.filter(source="monobank").count() == 1


def test_bad_token_message(client, yura, bank):
    client.force_login(yura.user)

    response = client.post(reverse("integrations:monobank_connect"), {"mono_token": "bad"}, follow=True)

    assert "не прийняв токен" in response.content.decode()


def test_cannot_sync_other_members_card(client, olya, mono, connection):
    card = link(connection, "black", mono)
    client.force_login(olya.user)

    assert client.post(reverse("integrations:monobank_sync", args=[card.pk])).status_code == 404


def test_disconnect_keeps_transactions(client, home, yura, mono, connection, bank):
    bank["black"] = [item("a1", -10000)]
    sync_account(link(connection, "black", mono), NOW)
    client.force_login(yura.user)

    client.post(reverse("integrations:monobank_disconnect"))

    assert not MonobankAccount.objects.exists()
    assert home.transactions.count() == 1


def test_link_can_create_account(client, home, yura, bank):
    client.force_login(yura.user)
    client.post(reverse("integrations:monobank_connect"), {"mono_token": "good"})
    connection = MonobankConnection.objects.get(membership=yura)
    black = connection.accounts.get(mono_id="black")
    jar = connection.accounts.get(mono_id="jar1")

    client.post(reverse("integrations:monobank_links"), {f"link_{black.pk}": "new", f"link_{jar.pk}": "new"})

    black.refresh_from_db()
    jar.refresh_from_db()
    assert (black.account.name, black.account.kind, black.account.owner) == ("Monobank Чорна", "card", yura)
    assert (jar.account.name, jar.account.kind) == ("Відпустка", "savings")


def test_created_account_name_is_unique(client, home, yura, bank):
    Account.objects.create(household=home, name="Monobank Чорна")
    client.force_login(yura.user)
    client.post(reverse("integrations:monobank_connect"), {"mono_token": "good"})
    black = MonobankConnection.objects.get(membership=yura).accounts.get(mono_id="black")

    client.post(reverse("integrations:monobank_links"), {f"link_{black.pk}": "new"})

    black.refresh_from_db()
    assert black.account.name == "Monobank Чорна 2"
