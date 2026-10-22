import datetime
import json
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.integrations import monobank
from apps.integrations.models import MonobankConnection
from apps.integrations.sync import connect


@pytest.fixture
def calls(monkeypatch):
    log = []

    def fake(token, path, payload=None):
        log.append((path, payload))
        if path == "/personal/client-info":
            return {"name": "Юрій", "accounts": [{"id": "black", "currencyCode": 980, "type": "black", "maskedPan": ["1234"]}]}
        return {}

    monkeypatch.setattr(monobank, "request", fake)
    return log


@pytest.fixture
def linked(calls, yura, mono):
    connection = connect(yura, "good")
    card = connection.accounts.get(mono_id="black")
    card.account = mono
    card.save()
    connection.webhook_secret = "s3cret"
    connection.save()
    return connection


def event(item_id, amount):
    moment = int(timezone.now().timestamp())
    return {"type": "StatementItem", "data": {"account": "black", "statementItem": {
        "id": item_id, "time": moment, "amount": amount, "description": "Сільпо", "mcc": 5411,
    }}}


def post(client, secret, payload):
    return client.post(reverse("integrations:monobank_webhook", args=[secret]), json.dumps(payload), content_type="application/json")


def test_webhook_check_and_unknown_secret(client, linked):
    assert client.get(reverse("integrations:monobank_webhook", args=["s3cret"])).status_code == 200
    assert client.get(reverse("integrations:monobank_webhook", args=["nope"])).status_code == 404


def test_webhook_creates_transaction_once(client, home, linked):
    assert post(client, "s3cret", event("w1", -48650)).json()["status"] == "created"
    assert post(client, "s3cret", event("w1", -48650)).json()["status"] == "duplicate"

    tx = home.transactions.get()
    assert (tx.amount, tx.category.name, tx.source) == (Decimal("486.50"), "Продукти", "monobank")


def test_webhook_ignores_unlinked_and_garbage(client, home, linked):
    linked.accounts.update(account=None)

    assert post(client, "s3cret", event("w1", -100)).json()["status"] == "ignored"
    assert post(client, "s3cret", {"type": "x"}).json()["status"] == "ignored"
    assert not home.transactions.exists()


def test_toggle_needs_https(client, yura, linked):
    client.force_login(yura.user)

    response = client.post(reverse("integrations:monobank_webhook_toggle"), follow=True)

    assert "лише на сайті з HTTPS" in response.content.decode()


def test_toggle_sets_and_removes_webhook(client, yura, calls, linked):
    linked.webhook_secret = ""
    linked.save()
    client.force_login(yura.user)

    client.post(reverse("integrations:monobank_webhook_toggle"), secure=True)
    linked.refresh_from_db()
    assert linked.webhook_secret
    path, payload = calls[-1]
    assert path == "/personal/webhook"
    assert payload["webHookUrl"].startswith("https://") and linked.webhook_secret in payload["webHookUrl"]

    client.post(reverse("integrations:monobank_webhook_toggle"), secure=True)
    linked.refresh_from_db()
    assert linked.webhook_secret == ""
    assert calls[-1] == ("/personal/webhook", {"webHookUrl": ""})
