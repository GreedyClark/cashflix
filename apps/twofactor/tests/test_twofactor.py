import json
import time

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.twofactor import devices, telegram, totp
from apps.twofactor.models import BackupCode, SecondFactor, TelegramRequest, TrustedDevice

SECRET = "JBSWY3DPEHPK3PXP"


@pytest.fixture
def user(yura):
    return yura.user


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake(method, payload=None):
        calls.append((method, payload or {}))
        if method == "getMe":
            return {"username": "CashFlixBot"}
        if method == "sendMessage":
            return {"message_id": 77}
        if method == "getUpdates":
            return []
        return True

    monkeypatch.setattr(telegram, "call", fake)
    return calls


def with_totp(user):
    factor = SecondFactor.of(user)
    factor.totp_secret = SECRET
    factor.method = SecondFactor.Method.TOTP
    factor.save()
    return factor


def current_code():
    return totp.code_at(SECRET, int(time.time() // totp.STEP))


def test_totp_matches_rfc_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp.code_at(secret, 59 // 30) == "287082"


def test_totp_rejects_reused_step():
    step = int(time.time() // totp.STEP)
    code = totp.code_at(SECRET, step)
    assert totp.matching_step(SECRET, code) == step
    assert totp.matching_step(SECRET, code, last_step=step) is None


def test_without_second_factor_pages_open(client, user):
    client.force_login(user)
    assert client.get(reverse("core:home")).status_code == 200


def test_gate_redirects_until_code_entered(client, user):
    with_totp(user)
    client.force_login(user)

    response = client.get(reverse("money:transactions"))
    assert response.status_code == 302 and response.url == reverse("twofactor:confirm")

    response = client.post(reverse("twofactor:confirm"), {"code": current_code()})
    assert response.url == reverse("money:transactions")
    assert client.get(reverse("money:transactions")).status_code == 200


def test_htmx_request_gets_hx_redirect(client, user):
    with_totp(user)
    client.force_login(user)

    response = client.get(reverse("money:transactions"), headers={"HX-Request": "true"})

    assert response["HX-Redirect"] == reverse("twofactor:confirm")


def test_wrong_codes_lock_after_five_attempts(client, user):
    with_totp(user)
    client.force_login(user)
    for _attempt in range(5):
        client.post(reverse("twofactor:confirm"), {"code": "000000"})

    response = client.post(reverse("twofactor:confirm"), {"code": current_code()})

    assert "Забагато спроб" in response.content.decode()


def test_trusted_device_skips_second_step(client, user):
    with_totp(user)
    client.force_login(user)
    client.post(reverse("twofactor:confirm"), {"code": current_code(), "trust": "on"})
    assert TrustedDevice.objects.filter(user=user).count() == 1
    cookie = client.cookies[devices.COOKIE]

    client.logout()
    client.cookies[devices.COOKIE] = cookie.value
    client.force_login(user)

    assert client.get(reverse("money:transactions")).status_code == 200


def test_forgotten_device_asks_again(client, user):
    with_totp(user)
    client.force_login(user)
    client.post(reverse("twofactor:confirm"), {"code": current_code(), "trust": "on"})
    cookie = client.cookies[devices.COOKIE]
    TrustedDevice.objects.all().delete()
    client.logout()
    client.cookies[devices.COOKIE] = cookie.value
    client.force_login(user)

    assert client.get(reverse("money:transactions")).status_code == 302


def test_cookie_of_other_user_is_ignored(rf, user, olya):
    request = rf.get("/")
    response = __import__("django.http", fromlist=["HttpResponse"]).HttpResponse()
    devices.trust(request, response, olya.user)
    request.COOKIES[devices.COOKIE] = response.cookies[devices.COOKIE].value

    assert devices.current(request, user) is None


def test_backup_code_works_once(client, user):
    with_totp(user)
    codes = BackupCode.issue(user)
    client.force_login(user)

    response = client.post(reverse("twofactor:confirm_backup"), {"code": codes[0].upper()})
    assert response.status_code == 302
    assert BackupCode.left(user) == 9

    client.logout()
    client.force_login(user)
    response = client.post(reverse("twofactor:confirm_backup"), {"code": codes[0]})
    assert "вже використано" in response.content.decode()


def test_totp_setup_enables_and_shows_codes(client, user):
    client.force_login(user)
    client.get(reverse("twofactor:totp"))
    secret = client.session["twofactor_totp"]
    code = totp.code_at(secret, int(time.time() // totp.STEP))

    response = client.post(reverse("twofactor:totp"), {"code": code})

    assert response.url == reverse("twofactor:security")
    factor = SecondFactor.objects.get(user=user)
    assert factor.method == SecondFactor.Method.TOTP and factor.totp_secret == secret
    page = client.get(reverse("twofactor:security")).content.decode()
    assert "Збережіть резервні коди" in page
    assert BackupCode.left(user) == 10


def test_disable_removes_devices_and_codes(client, user):
    with_totp(user)
    BackupCode.issue(user)
    client.force_login(user)
    client.post(reverse("twofactor:confirm"), {"code": current_code(), "trust": "on"})

    client.post(reverse("twofactor:choose"), {"method": "none"})

    assert SecondFactor.objects.get(user=user).method == "none"
    assert not TrustedDevice.objects.exists() and not BackupCode.objects.exists()


@override_settings(TELEGRAM_BOT_TOKEN="123:abc")
def test_telegram_link_flow(client, user, sent):
    client.force_login(user)
    page = client.get(reverse("twofactor:telegram")).content.decode()
    link = TelegramRequest.objects.get(kind="link")
    assert f"t.me/CashFlixBot?start={link.code}" in page

    webhook = client.post(
        reverse("twofactor:telegram_webhook"),
        json.dumps({"message": {"text": f"/start {link.code}", "chat": {"id": 555, "type": "private"}, "from": {"id": 555, "username": "yura_k"}}}),
        content_type="application/json",
        headers={"X-Telegram-Bot-Api-Secret-Token": telegram.webhook_secret()},
    )
    assert webhook.status_code == 200

    status = client.get(reverse("twofactor:telegram_status"))
    assert status["HX-Redirect"] == reverse("twofactor:security")
    factor = SecondFactor.objects.get(user=user)
    assert (factor.method, factor.telegram_chat_id, factor.telegram_username) == ("telegram", 555, "yura_k")


@override_settings(TELEGRAM_BOT_TOKEN="123:abc")
def test_telegram_webhook_needs_secret(client, sent):
    response = client.post(reverse("twofactor:telegram_webhook"), "{}", content_type="application/json")
    assert response.status_code == 403


@override_settings(TELEGRAM_BOT_TOKEN="123:abc")
def test_telegram_login_approve(client, user, sent):
    factor = SecondFactor.of(user)
    factor.telegram_chat_id = 555
    factor.method = SecondFactor.Method.TELEGRAM
    factor.save()
    client.force_login(user)

    client.get(reverse("twofactor:confirm"))
    login = TelegramRequest.objects.get(kind="login")
    assert any(method == "sendMessage" and payload["chat_id"] == 555 for method, payload in sent)
    assert client.get(reverse("twofactor:confirm_status")).status_code == 204

    stranger = {"callback_query": {"id": "q0", "data": f"ok:{login.code}", "from": {"id": 999}, "message": {"message_id": 77}}}
    client.post(reverse("twofactor:telegram_webhook"), json.dumps(stranger), content_type="application/json",
                headers={"X-Telegram-Bot-Api-Secret-Token": telegram.webhook_secret()})
    login.refresh_from_db()
    assert login.status == "pending"

    owner = {"callback_query": {"id": "q1", "data": f"ok:{login.code}", "from": {"id": 555}, "message": {"message_id": 77}}}
    client.post(reverse("twofactor:telegram_webhook"), json.dumps(owner), content_type="application/json",
                headers={"X-Telegram-Bot-Api-Secret-Token": telegram.webhook_secret()})

    response = client.get(reverse("twofactor:confirm_status"), {"trust": "on"})
    assert "twofactorDone" in response["HX-Trigger"]
    assert devices.COOKIE in response.cookies
    assert client.get(reverse("money:transactions")).status_code == 200


@override_settings(TELEGRAM_BOT_TOKEN="123:abc")
def test_telegram_login_deny_logs_out(client, user, sent):
    factor = SecondFactor.of(user)
    factor.telegram_chat_id = 555
    factor.method = SecondFactor.Method.TELEGRAM
    factor.save()
    client.force_login(user)
    client.get(reverse("twofactor:confirm"))
    login = TelegramRequest.objects.get(kind="login")

    deny = {"callback_query": {"id": "q1", "data": f"no:{login.code}", "from": {"id": 555}, "message": {"message_id": 77}}}
    client.post(reverse("twofactor:telegram_webhook"), json.dumps(deny), content_type="application/json",
                headers={"X-Telegram-Bot-Api-Secret-Token": telegram.webhook_secret()})
    response = client.get(reverse("twofactor:confirm_status"))

    assert response["HX-Redirect"] == reverse("account_login")
    assert "_auth_user_id" not in client.session


def test_security_page_renders(client, user):
    client.force_login(user)
    page = client.get(reverse("twofactor:security")).content.decode()
    assert "Другий крок після Google" in page
