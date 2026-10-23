import hashlib
import secrets

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.households.models import Membership
from apps.money.models import Account

from .crypto import decrypt, encrypt


def hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class ShortcutTokenQuerySet(models.QuerySet):
    def find(self, raw):
        if not raw:
            return None
        return self.filter(token_hash=hash_token(raw), membership__left_at__isnull=True).select_related(
            "membership__household", "membership__user", "account"
        ).first()


class ShortcutToken(models.Model):
    membership = models.OneToOneField(
        Membership, on_delete=models.CASCADE, related_name="shortcut_token", verbose_name=_("учасник")
    )
    token_hash = models.CharField(max_length=64, unique=True)
    prefix = models.CharField(_("початок токена"), max_length=8)
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("рахунок за замовчуванням"),
    )
    created_at = models.DateTimeField(_("створено"), auto_now_add=True)
    last_used_at = models.DateTimeField(_("останнє використання"), null=True, blank=True)

    objects = ShortcutTokenQuerySet.as_manager()

    class Meta:
        verbose_name = _("токен шорткату")
        verbose_name_plural = _("токени шорткату")

    def __str__(self):
        return f"{self.membership} · {self.prefix}…"

    @classmethod
    def issue(cls, membership):
        raw = "cf_" + secrets.token_urlsafe(24)
        token, created = cls.objects.update_or_create(
            membership=membership, defaults={"token_hash": hash_token(raw), "prefix": raw[:8], "last_used_at": None}
        )
        return token, raw

    def touch(self):
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])


class MonobankConnection(models.Model):
    membership = models.OneToOneField(
        Membership, on_delete=models.CASCADE, related_name="monobank", verbose_name=_("учасник")
    )
    token_encrypted = models.TextField()
    client_name = models.CharField(_("ім'я в банку"), max_length=120, blank=True)
    webhook_secret = models.CharField(max_length=64, blank=True, db_index=True)
    last_request_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(_("підключено"), auto_now_add=True)

    class Meta:
        verbose_name = _("підключення Monobank")
        verbose_name_plural = _("підключення Monobank")

    def __str__(self):
        return f"Monobank · {self.membership}"

    @property
    def token(self):
        return decrypt(self.token_encrypted)

    @token.setter
    def token(self, raw):
        self.token_encrypted = encrypt(raw)

    def seconds_to_wait(self, pause, now=None):
        if not self.last_request_at:
            return 0
        passed = ((now or timezone.now()) - self.last_request_at).total_seconds()
        return max(0, int(pause - passed) + 1)


class MonobankAccount(models.Model):
    connection = models.ForeignKey(
        MonobankConnection, on_delete=models.CASCADE, related_name="accounts", verbose_name=_("підключення")
    )
    mono_id = models.CharField(max_length=64)
    is_jar = models.BooleanField(default=False)
    title = models.CharField(_("назва"), max_length=120)
    currency = models.CharField(_("валюта"), max_length=3)
    account = models.OneToOneField(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="monobank",
        verbose_name=_("рахунок CashFlix"),
    )
    synced_until = models.DateTimeField(_("підтягнуто до"), null=True, blank=True)

    class Meta:
        verbose_name = _("картка Monobank")
        verbose_name_plural = _("картки Monobank")
        ordering = ["is_jar", "title"]
        constraints = [
            models.UniqueConstraint(fields=["connection", "mono_id"], name="unique_monobank_account"),
        ]

    def __str__(self):
        return self.title

    @property
    def suggested_name(self):
        if self.is_jar:
            return self.title.split("«", 1)[-1].rstrip("»") or self.title
        return f"Monobank {self.title.split(' ·· ')[0]}"
