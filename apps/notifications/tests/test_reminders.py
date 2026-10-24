import datetime
import json
from decimal import Decimal

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.notifications import push, reminders
from apps.notifications.models import NotifySettings, PushSubscription
from apps.recurring.models import RecurringPayment
from apps.recurring.services import run_due_payments
from apps.twofactor import telegram
from apps.twofactor.models import SecondFactor, TelegramRequest

TODAY = datetime.date(2026, 10, 25)
NINE = timezone.make_aware(datetime.datetime(2026, 10, 25, 9, 5))


@pytest.fixture
def flat(home, mono, yura):
    rent = home.categories.get(kind="expense", name="Комуналка")
    return RecurringPayment.objects.create(
        household=home, title="Квартира", amount=Decimal("400"), currency="USD", account=mono, category=rent,
        member=yura, start_date=TODAY, mode=RecurringPayment.Mode.REMIND, reminders=[3, 0],
    )


@pytest.fixture
def linked(yura):
    factor = SecondFactor.of(yura.user)
    factor.telegram_chat_id = 555
    factor.save()
    return factor


@pytest.fixture
def outbox(monkeypatch):
    sent = []

    def fake(method, payload=None):
        sent.append((method, payload or {}))
        if method == "sendMessage":
            return {"message_id": 1}
        return True

    monkeypatch.setattr(telegram, "call", fake)
    return sent


def messages_of(outbox):
    return [payload for method, payload in outbox if method == "sendMessage"]


def test_foreign_payment_converts_on_payment_day(flat, usd_rate):
    assert flat.pay_currency == "USD" and flat.is_foreign
    assert flat.account_amount(TODAY) == Decimal("16528.00")


def test_manual_payments_are_not_recorded_automatically(flat, home):
    assert run_due_payments(TODAY) == []
    assert not home.transactions.exists()


def test_auto_foreign_payment_is_converted(flat, home, usd_rate):
    flat.mode = RecurringPayment.Mode.AUTO
    flat.save()

    run_due_payments(TODAY)

    assert home.transactions.get().amount == Decimal("16528.00")


def test_due_items_follow_chosen_days(flat, yura):
    assert [item.days for item in reminders.due_items(yura.user, TODAY)] == [0]
    assert [item.days for item in reminders.due_items(yura.user, TODAY - datetime.timedelta(days=3))] == [3]
    assert reminders.due_items(yura.user, TODAY - datetime.timedelta(days=1)) == []
    assert [item.when for item in reminders.due_items(yura.user, TODAY + datetime.timedelta(days=2))] == ["Прострочено 2 дн."]


def test_snoozed_payment_reminds_that_day(flat, yura):
    flat.remind_on = TODAY - datetime.timedelta(days=1)
    flat.save()
    assert len(reminders.due_items(yura.user, TODAY - datetime.timedelta(days=1))) == 1


def test_other_member_does_not_get_personal_payment(flat, olya):
    assert reminders.due_items(olya.user, TODAY) == []


@override_settings(TELEGRAM_BOT_TOKEN="123:abc")
def test_send_reminders_once_after_chosen_time(flat, yura, linked, outbox, usd_rate):
    early = timezone.make_aware(datetime.datetime(2026, 10, 25, 8, 30))
    assert reminders.send_reminders(early) == 0

    assert reminders.send_reminders(NINE) == 1
    assert reminders.send_reminders(NINE + datetime.timedelta(hours=1)) == 0

    message = messages_of(outbox)[0]
    assert "Квартира" in message["text"] and "$400" in message["text"]
    buttons = message["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == f"pay:{flat.pk}:20261025"


@override_settings(TELEGRAM_BOT_TOKEN="123:abc")
def test_custom_time_is_respected(flat, yura, linked, outbox):
    settings_row = NotifySettings.of(yura.user)
    settings_row.remind_at = datetime.time(20, 15)
    settings_row.save()

    assert reminders.send_reminders(NINE) == 0
    assert reminders.send_reminders(timezone.make_aware(datetime.datetime(2026, 10, 25, 20, 20))) == 1


def press(client, data, sender=555):
    update = {"callback_query": {"id": "q", "data": data, "from": {"id": sender}, "message": {"message_id": 1}}}
    return client.post(
        reverse("twofactor:telegram_webhook"), json.dumps(update), content_type="application/json",
        headers={"X-Telegram-Bot-Api-Secret-Token": telegram.webhook_secret()},
    )


@override_settings(TELEGRAM_BOT_TOKEN="123:abc")
def test_paid_button_records_payment_once(client, flat, home, linked, outbox, usd_rate, monkeypatch):
    monkeypatch.setattr(timezone, "localdate", lambda *args: TODAY)

    press(client, f"pay:{flat.pk}:20261025")
    press(client, f"pay:{flat.pk}:20261025")

    tx = home.transactions.get()
    assert (tx.amount, tx.date, tx.title) == (Decimal("16528.00"), TODAY, "Квартира")
    flat.refresh_from_db()
    assert flat.next_date == datetime.date(2026, 11, 25)


@override_settings(TELEGRAM_BOT_TOKEN="123:abc")
def test_stranger_cannot_press_paid(client, flat, home, linked, outbox):
    press(client, f"pay:{flat.pk}:20261025", sender=999)
    assert not home.transactions.exists()


@override_settings(TELEGRAM_BOT_TOKEN="123:abc")
def test_snooze_button(client, flat, linked, outbox):
    press(client, f"snooze:{flat.pk}")
    flat.refresh_from_db()
    assert flat.remind_on == timezone.localdate() + datetime.timedelta(days=1)


def test_payment_form_saves_currency_mode_and_days(client, home, yura, mono):
    client.force_login(yura.user)
    rent = home.categories.get(kind="expense", name="Комуналка")

    client.post(reverse("recurring:payment_create"), {
        "type": "expense", "title": "Квартира", "amount": "400", "currency": "USD", "account": mono.pk,
        "category": rent.pk, "member": "", "period": "monthly", "start_date": "2026-11-01",
        "mode": "remind", "reminders": ["0", "3"],
    })

    payment = RecurringPayment.objects.get()
    assert (payment.currency, payment.mode, payment.reminders) == ("USD", "remind", [3, 0])


def test_same_currency_as_account_is_stored_empty(client, home, yura, mono):
    client.force_login(yura.user)
    rent = home.categories.get(kind="expense", name="Комуналка")

    client.post(reverse("recurring:payment_create"), {
        "type": "expense", "title": "Інтернет", "amount": "250", "currency": "UAH", "account": mono.pk,
        "category": rent.pk, "member": "", "period": "monthly", "start_date": "2026-11-01",
    })

    assert RecurringPayment.objects.get().currency == ""


def test_push_subscription_saved_and_validated(client, yura):
    client.force_login(yura.user)
    good = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "key", "auth": "secret"}}

    assert client.post(reverse("notifications:subscribe"), json.dumps(good), content_type="application/json").status_code == 200
    assert client.post(reverse("notifications:subscribe"), json.dumps({"endpoint": "http://x"}), content_type="application/json").status_code == 400
    assert PushSubscription.objects.get().user == yura.user


@override_settings(VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv")
def test_push_reminder_sent(flat, yura, monkeypatch, usd_rate):
    PushSubscription.objects.create(user=yura.user, endpoint="https://push.example/1", p256dh="k", auth="a")
    sent = []
    monkeypatch.setattr(push, "webpush", lambda **kwargs: sent.append(json.loads(kwargs["data"])))

    assert reminders.send_reminders(NINE) == 1
    assert sent[0]["title"] == "Сьогодні оплатити"


def test_settings_page_and_time(client, yura):
    client.force_login(yura.user)
    assert "О котрій нагадувати" in client.get(reverse("notifications:settings")).content.decode()

    client.post(reverse("notifications:settings"), {"remind_at": "07:45"})

    assert NotifySettings.of(yura.user).remind_at == datetime.time(7, 45)


def test_pwa_files_are_public(client):
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and manifest.json()["display"] == "standalone"
    worker = client.get("/sw.js")
    assert worker.status_code == 200 and worker["Service-Worker-Allowed"] == "/"


@override_settings(TELEGRAM_BOT_TOKEN="123:abc")
def test_telegram_for_notifications_does_not_enable_two_factor(client, yura, outbox, monkeypatch):
    monkeypatch.setattr(telegram, "bot_username", lambda: "CashFlixBot")
    client.force_login(yura.user)
    client.get(reverse("twofactor:telegram") + "?for=notify")
    link = TelegramRequest.objects.get()
    client.post(
        reverse("twofactor:telegram_webhook"),
        json.dumps({"message": {"text": f"/start {link.code}", "chat": {"id": 555, "type": "private"}, "from": {"id": 555}}}),
        content_type="application/json", headers={"X-Telegram-Bot-Api-Secret-Token": telegram.webhook_secret()},
    )

    response = client.get(reverse("twofactor:telegram_status"))

    assert response["HX-Redirect"] == reverse("notifications:settings")
    factor = SecondFactor.objects.get(user=yura.user)
    assert (factor.telegram_chat_id, factor.method) == (555, "none")
