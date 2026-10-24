import datetime

from django.utils import timezone

from apps.core.templatetags.money import money
from apps.money.rates import RateNotFound
from apps.recurring.services import pay_now
from apps.twofactor import telegram
from apps.twofactor.models import SecondFactor

from .reminders import payments_for

ACTIONS = ("pay", "snooze")


def handle_button(query):
    action, _sep, rest = (query.get("data") or "").partition(":")
    sender = (query.get("from") or {}).get("id")
    factor = SecondFactor.objects.filter(telegram_chat_id=sender).select_related("user").first() if sender else None
    if factor is None:
        telegram.answer(query["id"], "Не знайшли ваш акаунт CashFlix")
        return
    payment_id, _sep, stamp = rest.partition(":")
    payment = payments_for(factor.user).filter(pk=payment_id).first() if payment_id.isdigit() else None
    if payment is None:
        telegram.answer(query["id"], "Платіж не знайдено")
        return
    today = timezone.localdate()
    if action == "snooze":
        payment.remind_on = today + datetime.timedelta(days=1)
        payment.save(update_fields=["remind_on"])
        telegram.answer(query["id"], "Нагадаю завтра")
        return
    if payment.next_date.strftime("%Y%m%d") != stamp:
        telegram.answer(query["id"], "Цей платіж уже записано")
        return
    try:
        amount = payment.account_amount(today)
    except RateNotFound:
        telegram.answer(query["id"], "Немає курсу валюти, запишіть оплату на сайті")
        return
    pay_now(payment, amount, today)
    telegram.answer(query["id"], "Записано")
    telegram.send(sender, f"✅ {payment.title}: записано {money(amount, payment.account.currency)}")
