import hashlib
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 10


class TelegramError(Exception):
    pass


def configured():
    return bool(settings.TELEGRAM_BOT_TOKEN)


def call(method, payload=None):
    if not configured():
        raise TelegramError("not configured")
    request = urllib.request.Request(
        API.format(token=settings.TELEGRAM_BOT_TOKEN, method=method),
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        log.warning("Telegram %s failed: %s", method, error)
        raise TelegramError(str(error)) from error
    if not data.get("ok"):
        raise TelegramError(data.get("description", "error"))
    return data.get("result")


def webhook_secret():
    return hashlib.sha256(f"telegram:{settings.SECRET_KEY}".encode()).hexdigest()[:48]


def bot_username():
    name = cache.get("telegram_bot_username")
    if name is None:
        name = call("getMe").get("username", "")
        cache.set("telegram_bot_username", name, 60 * 60 * 24)
    return name


def ensure_webhook(url):
    if cache.get("telegram_webhook") == url:
        return
    call("setWebhook", {"url": url, "secret_token": webhook_secret(), "allowed_updates": ["message", "callback_query"]})
    cache.set("telegram_webhook", url, 60 * 60 * 24)


def pull_updates():
    offset = cache.get("telegram_offset", 0)
    updates = call("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": ["message", "callback_query"]})
    for update in updates or []:
        cache.set("telegram_offset", update["update_id"] + 1, None)
        yield update


def send(chat_id, text, buttons=None, rows=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    keyboard = ([buttons] if buttons else []) + (rows or [])
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return call("sendMessage", payload)


def edit(chat_id, message_id, text):
    try:
        call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"})
    except TelegramError:
        pass


def answer(callback_id, text):
    try:
        call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
    except TelegramError:
        pass
