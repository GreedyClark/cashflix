import secrets
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone

from .models import TrustedDevice, digest

COOKIE = "cf_trust"
SALT = "cashflix.trusted-device"
TRUST_DAYS = 30
SYSTEMS = [("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("Mac OS", "Mac"), ("Linux", "Linux")]
BROWSERS = [("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("CriOS", "Chrome"), ("Chrome/", "Chrome"), ("Safari/", "Safari")]


def label(request):
    agent = request.headers.get("User-Agent", "")
    system = next((name for marker, name in SYSTEMS if marker in agent), "")
    browser = next((name for marker, name in BROWSERS if marker in agent), "")
    return " · ".join(part for part in (system, browser) if part) or "Невідомий пристрій"


def trust(request, response, user):
    raw = secrets.token_urlsafe(24)
    expires = timezone.now() + timedelta(days=TRUST_DAYS)
    TrustedDevice.objects.create(user=user, key_hash=digest(raw), label=label(request), expires_at=expires)
    response.set_cookie(
        COOKIE,
        signing.dumps({"u": user.pk, "k": raw}, salt=SALT),
        max_age=TRUST_DAYS * 24 * 3600,
        secure=not settings.DEBUG,
        httponly=True,
        samesite="Lax",
    )


def current(request, user):
    value = request.COOKIES.get(COOKIE)
    if not value:
        return None
    try:
        data = signing.loads(value, salt=SALT, max_age=TRUST_DAYS * 24 * 3600)
    except signing.BadSignature:
        return None
    if data.get("u") != user.pk:
        return None
    return TrustedDevice.objects.filter(user=user, key_hash=digest(data.get("k", "")), expires_at__gt=timezone.now()).first()


def recognize(request, user):
    device = current(request, user)
    if device:
        device.last_seen_at = timezone.now()
        device.save(update_fields=["last_seen_at"])
    return device
