import hmac
import json
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import bot, devices, telegram, totp
from .gate import mark_passed, passed
from .models import BackupCode, SecondFactor, TelegramRequest, TrustedDevice

MAX_ATTEMPTS = 5
LOCK_SECONDS = 300
LINK_KEY = "twofactor_link"
LOGIN_KEY = "twofactor_login"
SETUP_KEY = "twofactor_totp"
CODES_KEY = "twofactor_codes"
NEXT_KEY = "twofactor_next"


def hx_redirect(url):
    response = HttpResponse(status=204)
    response["HX-Redirect"] = url
    return response


def next_url(request):
    url = request.session.pop(NEXT_KEY, "")
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return reverse("core:home")


def locked(request):
    until = request.session.get("twofactor_lock", 0)
    return max(0, int(until - time.time()))


def failed(request):
    count = request.session.get("twofactor_fails", 0) + 1
    request.session["twofactor_fails"] = count
    if count >= MAX_ATTEMPTS:
        request.session["twofactor_lock"] = time.time() + LOCK_SECONDS
        request.session["twofactor_fails"] = 0


def lock_message(seconds):
    return _("Забагато спроб. Спробуйте через %(minutes)s хв.") % {"minutes": seconds // 60 + 1}


def sync_telegram(request):
    if not telegram.configured():
        return
    try:
        if request.is_secure():
            telegram.ensure_webhook(request.build_absolute_uri(reverse("twofactor:telegram_webhook")))
        elif settings.DEBUG:
            for update in telegram.pull_updates():
                bot.handle(update)
    except telegram.TelegramError:
        pass


def give_codes(request, user, force=False):
    if force or not BackupCode.objects.filter(user=user).exists():
        request.session[CODES_KEY] = BackupCode.issue(user)


def enable(request, factor, method):
    factor.method = method
    factor.save(update_fields=["method", "updated_at"])
    give_codes(request, factor.user)
    mark_passed(request)


def security(request):
    factor = SecondFactor.of(request.user)
    current = devices.current(request, request.user)
    trusted = list(request.user.trusted_devices.filter(expires_at__gt=timezone.now()))
    for device in trusted:
        device.is_current = current is not None and device.pk == current.pk
    return render(request, "twofactor/security.html", {
        "factor": factor,
        "methods": SecondFactor.Method,
        "telegram_ready": telegram.configured(),
        "trusted": trusted,
        "codes_left": BackupCode.left(request.user),
        "new_codes": request.session.pop(CODES_KEY, None),
    })


@require_POST
def choose(request):
    factor = SecondFactor.of(request.user)
    method = request.POST.get("method")
    if method == SecondFactor.Method.NONE:
        factor.method = method
        factor.save(update_fields=["method", "updated_at"])
        request.user.trusted_devices.all().delete()
        BackupCode.objects.filter(user=request.user).delete()
        messages.success(request, _("Другий крок вимкнено. Вхід лише через Google."))
    elif method == SecondFactor.Method.TELEGRAM:
        if not factor.has_telegram:
            return redirect("twofactor:telegram")
        enable(request, factor, method)
        messages.success(request, _("Тепер вхід підтверджується в Telegram."))
    elif method == SecondFactor.Method.TOTP:
        if not factor.has_totp:
            return redirect("twofactor:totp")
        enable(request, factor, method)
        messages.success(request, _("Тепер вхід підтверджується кодом із Google Authenticator."))
    return redirect("twofactor:security")


def telegram_link(request):
    if not telegram.configured():
        messages.error(request, _("Бот Telegram ще не налаштовано: додайте TELEGRAM_BOT_TOKEN."))
        return redirect("twofactor:security")
    sync_telegram(request)
    try:
        username = telegram.bot_username()
    except telegram.TelegramError:
        messages.error(request, _("Telegram зараз недоступний. Спробуйте пізніше."))
        return redirect("twofactor:security")
    link = TelegramRequest.start(request.user, TelegramRequest.Kind.LINK)
    request.session[LINK_KEY] = link.pk
    return render(request, "twofactor/telegram_link.html", {"bot": username, "link": f"https://t.me/{username}?start={link.code}"})


def telegram_link_status(request):
    sync_telegram(request)
    found = TelegramRequest.objects.filter(pk=request.session.get(LINK_KEY), user=request.user).first()
    if found and found.status == TelegramRequest.Status.APPROVED:
        request.session.pop(LINK_KEY, None)
        enable(request, SecondFactor.of(request.user), SecondFactor.Method.TELEGRAM)
        messages.success(request, _("Telegram підключено. Тепер вхід підтверджується в боті."))
        return hx_redirect(reverse("twofactor:security"))
    if not found or found.expired:
        return render(request, "twofactor/_expired.html", {"retry": reverse("twofactor:telegram")}, status=286)
    return HttpResponse(status=204)


def totp_setup(request):
    secret = request.session.get(SETUP_KEY) or totp.new_secret()
    request.session[SETUP_KEY] = secret
    error = ""
    if request.method == "POST":
        wait = locked(request)
        step = None if wait else totp.matching_step(secret, request.POST.get("code"))
        if step:
            factor = SecondFactor.of(request.user)
            factor.totp_secret = secret
            factor.totp_last_step = step
            factor.save()
            request.session.pop(SETUP_KEY, None)
            enable(request, factor, SecondFactor.Method.TOTP)
            messages.success(request, _("Google Authenticator підключено."))
            return redirect("twofactor:security")
        if wait:
            error = lock_message(wait)
        else:
            failed(request)
            error = _("Код не підійшов. Перевірте час на телефоні й спробуйте новий код.")
    return render(request, "twofactor/totp_setup.html", {
        "qr": totp.qr_svg(totp.uri(secret, request.user.email)),
        "secret": totp.spaced(secret),
        "error": error,
    })


@require_POST
def new_codes(request):
    give_codes(request, request.user, force=True)
    return redirect("twofactor:security")


@require_POST
def forget_device(request, pk):
    get_object_or_404(TrustedDevice, pk=pk, user=request.user).delete()
    messages.success(request, _("Пристрій забуто. На ньому знову питатимемо другий крок."))
    return redirect("twofactor:security")


def finish(request, trust):
    request.session.pop(LOGIN_KEY, None)
    request.session.pop("twofactor_fails", None)
    mark_passed(request)
    return next_url(request), trust


def done_response(request, url, trust, htmx=False):
    if htmx:
        response = HttpResponse()
        response["HX-Trigger"] = json.dumps({"twofactorDone": {"url": url}})
    else:
        response = redirect(url)
    if trust:
        devices.trust(request, response, request.user)
    return response


def login_request(request, factor, fresh=False):
    found = None if fresh else TelegramRequest.objects.filter(pk=request.session.get(LOGIN_KEY), user=request.user).first()
    if found and not found.expired and found.status == TelegramRequest.Status.PENDING:
        return found, ""
    found = TelegramRequest.start(request.user, TelegramRequest.Kind.LOGIN, devices.label(request))
    request.session[LOGIN_KEY] = found.pk
    try:
        bot.ask_login(factor, found)
    except telegram.TelegramError:
        return found, _("Не вдалося надіслати запит у Telegram. Скористайтеся резервним кодом.")
    return found, ""


def confirm(request):
    factor = SecondFactor.of(request.user)
    if not factor.enabled or passed(request):
        return redirect(next_url(request))
    if factor.method == SecondFactor.Method.TELEGRAM:
        sync_telegram(request)
        _found, error = login_request(request, factor, fresh=request.method == "POST")
        return render(request, "twofactor/confirm_telegram.html", {"factor": factor, "error": error})

    error = ""
    if request.method == "POST":
        wait = locked(request)
        step = None if wait else totp.matching_step(factor.totp_secret, request.POST.get("code"), factor.totp_last_step)
        if step:
            factor.totp_last_step = step
            factor.save(update_fields=["totp_last_step", "updated_at"])
            url, trust = finish(request, request.POST.get("trust") == "on")
            return done_response(request, url, trust)
        if wait:
            error = lock_message(wait)
        else:
            failed(request)
            error = _("Код не підійшов. Введіть новий код із застосунку.")
    return render(request, "twofactor/confirm_totp.html", {"error": error})


def confirm_status(request):
    if passed(request):
        return HttpResponse(status=286)
    sync_telegram(request)
    found = TelegramRequest.objects.filter(pk=request.session.get(LOGIN_KEY), user=request.user).first()
    if found and found.status == TelegramRequest.Status.APPROVED and not found.expired:
        url, trust = finish(request, request.GET.get("trust") == "on")
        return done_response(request, url, trust, htmx=True)
    if found and found.status == TelegramRequest.Status.DENIED:
        logout(request)
        messages.error(request, _("Вхід скасовано з Telegram."))
        return hx_redirect(reverse("account_login"))
    if not found or found.expired:
        return render(request, "twofactor/_expired.html", {"retry": reverse("twofactor:confirm")}, status=286)
    return HttpResponse(status=204)


def confirm_backup(request):
    if not SecondFactor.of(request.user).enabled or passed(request):
        return redirect(next_url(request))
    error = ""
    if request.method == "POST":
        wait = locked(request)
        if not wait and BackupCode.use(request.user, request.POST.get("code")):
            left = BackupCode.left(request.user)
            messages.warning(request, _("Резервний код використано. Лишилось %(left)s.") % {"left": left})
            url, trust = finish(request, request.POST.get("trust") == "on")
            return done_response(request, url, trust)
        if wait:
            error = lock_message(wait)
        else:
            failed(request)
            error = _("Такого коду немає або його вже використано.")
    return render(request, "twofactor/confirm_backup.html", {"error": error})


@csrf_exempt
@login_not_required
@require_POST
def telegram_webhook(request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not telegram.configured() or not hmac.compare_digest(secret, telegram.webhook_secret()):
        return HttpResponse(status=403)
    try:
        update = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    if isinstance(update, dict):
        try:
            bot.handle(update)
        except telegram.TelegramError:
            pass
    return HttpResponse("ok")
