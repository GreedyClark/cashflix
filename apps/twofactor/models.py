import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.integrations.crypto import decrypt, encrypt

REQUEST_LIFETIME = timedelta(minutes=10)
BACKUP_COUNT = 10
BACKUP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class SecondFactor(models.Model):
    class Method(models.TextChoices):
        NONE = "none", _("Лише Google")
        TELEGRAM = "telegram", _("Telegram")
        TOTP = "totp", _("Google Authenticator")

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="second_factor")
    method = models.CharField(_("спосіб"), max_length=10, choices=Method.choices, default=Method.NONE)
    telegram_chat_id = models.BigIntegerField(null=True, blank=True)
    telegram_username = models.CharField(max_length=64, blank=True)
    totp_encrypted = models.TextField(blank=True)
    totp_last_step = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("другий крок входу")
        verbose_name_plural = _("другий крок входу")

    def __str__(self):
        return f"{self.user} · {self.method}"

    @property
    def enabled(self):
        return self.method != self.Method.NONE

    @property
    def has_telegram(self):
        return self.telegram_chat_id is not None

    @property
    def has_totp(self):
        return bool(self.totp_encrypted)

    @property
    def totp_secret(self):
        return decrypt(self.totp_encrypted) if self.totp_encrypted else ""

    @totp_secret.setter
    def totp_secret(self, value):
        self.totp_encrypted = encrypt(value) if value else ""

    @classmethod
    def of(cls, user):
        factor, _created = cls.objects.get_or_create(user=user)
        return factor


class BackupCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="backup_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("резервний код")
        verbose_name_plural = _("резервні коди")

    @staticmethod
    def normalize(code):
        return "".join(ch for ch in (code or "").lower() if ch.isalnum())

    @classmethod
    def issue(cls, user):
        cls.objects.filter(user=user).delete()
        codes = []
        for _index in range(BACKUP_COUNT):
            raw = "".join(secrets.choice(BACKUP_ALPHABET) for _char in range(8))
            codes.append(f"{raw[:4]}-{raw[4:]}")
        cls.objects.bulk_create(cls(user=user, code_hash=digest(f"{user.pk}:{cls.normalize(c)}")) for c in codes)
        return codes

    @classmethod
    def use(cls, user, code):
        found = cls.objects.filter(user=user, used_at__isnull=True, code_hash=digest(f"{user.pk}:{cls.normalize(code)}")).first()
        if not found:
            return False
        found.used_at = timezone.now()
        found.save(update_fields=["used_at"])
        return True

    @classmethod
    def left(cls, user):
        return cls.objects.filter(user=user, used_at__isnull=True).count()


class TrustedDevice(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trusted_devices")
    key_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField(_("пристрій"), max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("довірений пристрій")
        verbose_name_plural = _("довірені пристрої")
        ordering = ["-last_seen_at", "-created_at"]

    def __str__(self):
        return self.label


class TelegramRequest(models.Model):
    class Kind(models.TextChoices):
        LINK = "link", _("Підключення")
        LOGIN = "login", _("Вхід")

    class Status(models.TextChoices):
        PENDING = "pending", _("Очікує")
        APPROVED = "approved", _("Підтверджено")
        DENIED = "denied", _("Відхилено")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    code = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    device = models.CharField(max_length=80, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("запит Telegram")
        verbose_name_plural = _("запити Telegram")

    @classmethod
    def start(cls, user, kind, device=""):
        cls.objects.filter(user=user, kind=kind, status=cls.Status.PENDING).delete()
        return cls.objects.create(user=user, kind=kind, code=secrets.token_urlsafe(18), device=device)

    @classmethod
    def live(cls):
        return cls.objects.filter(created_at__gte=timezone.now() - REQUEST_LIFETIME)

    @property
    def expired(self):
        return self.created_at < timezone.now() - REQUEST_LIFETIME
