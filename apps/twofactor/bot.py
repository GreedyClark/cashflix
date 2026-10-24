from django.utils import formats, timezone

from . import telegram
from .models import SecondFactor, TelegramRequest

APPROVE = "ok"
DENY = "no"


def handle(update):
    if "callback_query" in update:
        on_button(update["callback_query"])
        return
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return
    text = (message.get("text") or "").strip()
    if text.startswith("/start "):
        on_start(chat["id"], message.get("from") or {}, text.split(maxsplit=1)[1])
    else:
        telegram.send(chat["id"], "Я надсилаю запити на вхід у CashFlix. Підключити мене можна на сторінці «Безпека входу».")


def on_start(chat_id, sender, code):
    found = TelegramRequest.live().filter(kind=TelegramRequest.Kind.LINK, code=code, status=TelegramRequest.Status.PENDING).first()
    if not found:
        telegram.send(chat_id, "Посилання застаріло. Відкрийте його ще раз зі сторінки «Безпека входу» в CashFlix.")
        return
    factor = SecondFactor.of(found.user)
    factor.telegram_chat_id = chat_id
    factor.telegram_username = sender.get("username", "")[:64]
    factor.save(update_fields=["telegram_chat_id", "telegram_username", "updated_at"])
    found.status = TelegramRequest.Status.APPROVED
    found.save(update_fields=["status"])
    telegram.send(chat_id, "Готово ✅ Тепер вхід у CashFlix підтверджується тут.")


def on_button(query):
    action, _sep, code = (query.get("data") or "").partition(":")
    found = TelegramRequest.objects.filter(kind=TelegramRequest.Kind.LOGIN, code=code).first()
    sender = (query.get("from") or {}).get("id")
    factor = SecondFactor.objects.filter(user_id=found.user_id).first() if found else None
    if not found or not factor or factor.telegram_chat_id != sender:
        telegram.answer(query["id"], "Запит не знайдено")
        return
    message = query.get("message") or {}
    if found.status != TelegramRequest.Status.PENDING or found.expired:
        telegram.answer(query["id"], "Цей запит уже не дійсний")
        return
    if action == APPROVE:
        found.status = TelegramRequest.Status.APPROVED
        text = f"✅ Вхід підтверджено\n{found.device}"
    else:
        found.status = TelegramRequest.Status.DENIED
        text = "⛔ Вхід скасовано. Якщо це були не ви, змініть пароль від Google."
    found.save(update_fields=["status"])
    telegram.answer(query["id"], "Готово")
    if message.get("message_id"):
        telegram.edit(sender, message["message_id"], text)


def ask_login(factor, request_obj):
    moment = formats.time_format(timezone.localtime(), "H:i")
    text = f"<b>Вхід у CashFlix</b>\n{request_obj.device} · {moment}\n\nЦе ви?"
    buttons = [
        {"text": "✅ Це я", "callback_data": f"{APPROVE}:{request_obj.code}"},
        {"text": "Не я", "callback_data": f"{DENY}:{request_obj.code}"},
    ]
    result = telegram.send(factor.telegram_chat_id, text, buttons)
    request_obj.message_id = (result or {}).get("message_id")
    request_obj.save(update_fields=["message_id"])
