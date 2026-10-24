import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.staticfiles import finders
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.twofactor import telegram
from apps.twofactor.devices import label
from apps.twofactor.models import SecondFactor

from . import push
from .forms import NotifyForm
from .models import NotifySettings, PushSubscription
from .reminders import deliver, due_items


def notify_settings(request):
    notify = NotifySettings.of(request.user)
    factor = SecondFactor.objects.filter(user=request.user).first()
    form = NotifyForm(request.POST or None, instance=notify)
    if request.method == "POST" and form.is_valid():
        if "remind_at" in form.changed_data:
            form.instance.last_sent_on = None
        if not (factor and factor.has_telegram):
            form.instance.telegram = True
        form.save()
        messages.success(request, _("Збережено."))
        return redirect("notifications:settings")
    context = {
        "form": form,
        "factor": factor,
        "telegram_ready": telegram.configured(),
        "push_ready": push.configured(),
        "vapid_key": settings.VAPID_PUBLIC_KEY,
        "subscriptions": request.user.push_subscriptions.all(),
        "upcoming": due_items(request.user, timezone.localdate()),
    }
    return render(request, "notifications/settings.html", context)


@require_POST
def subscribe(request):
    try:
        data = json.loads(request.body)
        endpoint = str(data["endpoint"])
        keys = data["keys"]
        p256dh, auth = str(keys["p256dh"]), str(keys["auth"])
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"status": "error"}, status=400)
    if not endpoint.startswith("https://") or len(endpoint) > 600 or len(p256dh) > 200 or len(auth) > 100:
        return JsonResponse({"status": "error"}, status=400)
    PushSubscription.objects.update_or_create(
        endpoint=endpoint, defaults={"user": request.user, "p256dh": p256dh, "auth": auth, "label": label(request)}
    )
    return JsonResponse({"status": "ok"})


@require_POST
def unsubscribe(request, pk):
    get_object_or_404(PushSubscription, pk=pk, user=request.user).delete()
    messages.success(request, _("Пристрій відключено від push."))
    return redirect("notifications:settings")


@require_POST
def test(request):
    factor = SecondFactor.objects.filter(user=request.user).first()
    chat_id = factor.telegram_chat_id if factor and NotifySettings.of(request.user).telegram else None
    sent = 0
    if chat_id:
        try:
            telegram.send(chat_id, "🔔 Тестове нагадування CashFlix. Усе працює!")
            sent += 1
        except telegram.TelegramError:
            pass
    if push.configured():
        sent += push.send_all(request.user, "CashFlix", _("Тестове нагадування. Усе працює!"))
    if sent:
        messages.success(request, _("Надіслано. Перевірте телефон."))
    else:
        messages.error(request, _("Немає куди надсилати: підключіть Telegram або увімкніть push."))
    return redirect("notifications:settings")


@require_POST
def remind_now(request):
    items = due_items(request.user, timezone.localdate())
    factor = SecondFactor.objects.filter(user=request.user).first()
    chat_id = factor.telegram_chat_id if factor and NotifySettings.of(request.user).telegram else None
    if items and deliver(request.user, items, chat_id):
        messages.success(request, _("Нагадування надіслано."))
    else:
        messages.error(request, _("Сьогодні нагадувати нічого або немає куди надсилати."))
    return redirect("notifications:settings")


@login_not_required
def service_worker(request):
    with open(finders.find("js/sw.js"), "rb") as source:
        response = HttpResponse(source.read(), content_type="text/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@login_not_required
def manifest(request):
    from django.templatetags.static import static

    data = {
        "name": "CashFlix",
        "short_name": "CashFlix",
        "description": "Сімейний бюджет",
        "lang": "uk",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#08090b",
        "theme_color": "#08090b",
        "icons": [
            {"src": static("icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": static("icons/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})
