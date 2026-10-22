import hashlib
import secrets

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.households.models import Membership
from apps.money.models import Account


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
