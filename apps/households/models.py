import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Currency(models.TextChoices):
    UAH = "UAH", _("Гривня")
    USD = "USD", _("Долар США")
    EUR = "EUR", _("Євро")


class HouseholdQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(memberships__user=user, memberships__left_at__isnull=True)


class Household(models.Model):
    name = models.CharField(_("назва"), max_length=100)
    base_currency = models.CharField(
        _("основна валюта"), max_length=3, choices=Currency.choices, default=Currency.UAH
    )
    created_at = models.DateTimeField(_("створено"), auto_now_add=True)

    objects = HouseholdQuerySet.as_manager()

    class Meta:
        verbose_name = _("господарство")
        verbose_name_plural = _("господарства")

    def __str__(self):
        return self.name


class MembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(left_at__isnull=True)

    def former(self):
        return self.filter(left_at__isnull=False)


class Membership(models.Model):
    MAX_COLOR_SLOTS = 7

    class Role(models.TextChoices):
        OWNER = "owner", _("власник")
        MEMBER = "member", _("учасник")

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="memberships", verbose_name=_("господарство")
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("користувач"),
    )
    role = models.CharField(_("роль"), max_length=10, choices=Role.choices, default=Role.MEMBER)
    color_slot = models.PositiveSmallIntegerField(_("колір"), default=1)
    joined_at = models.DateTimeField(_("приєднався"), auto_now_add=True)
    left_at = models.DateTimeField(_("вийшов"), null=True, blank=True)

    objects = MembershipQuerySet.as_manager()

    class Meta:
        verbose_name = _("учасник")
        verbose_name_plural = _("учасники")
        ordering = ["joined_at"]
        constraints = [
            models.UniqueConstraint(fields=["household", "user"], name="unique_membership"),
        ]

    def __str__(self):
        return f"{self.user} — {self.household}"

    @property
    def is_active(self):
        return self.left_at is None

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER

    @property
    def color_var(self):
        return f"--cat-{self.color_slot}"


def make_token():
    return secrets.token_urlsafe(16)


def default_expiry():
    return timezone.now() + timedelta(days=Invitation.LIFETIME_DAYS)


class InvitationQuerySet(models.QuerySet):
    def active(self):
        return self.filter(accepted_at__isnull=True, is_revoked=False, expires_at__gt=timezone.now())


class Invitation(models.Model):
    LIFETIME_DAYS = 7

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="invitations", verbose_name=_("господарство")
    )
    token = models.CharField(max_length=32, unique=True, default=make_token, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_invitations",
        verbose_name=_("хто запросив"),
    )
    created_at = models.DateTimeField(_("створено"), auto_now_add=True)
    expires_at = models.DateTimeField(_("діє до"), default=default_expiry)
    is_revoked = models.BooleanField(_("скасовано"), default=False)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_invitations",
        verbose_name=_("хто приєднався"),
    )
    accepted_at = models.DateTimeField(_("приєднався"), null=True, blank=True)

    objects = InvitationQuerySet.as_manager()

    class Meta:
        verbose_name = _("запрошення")
        verbose_name_plural = _("запрошення")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.household} ({self.token[:6]}…)"

    def get_absolute_url(self):
        return reverse("households:join", args=[self.token])

    @property
    def is_active(self):
        return self.accepted_at is None and not self.is_revoked and self.expires_at > timezone.now()

    @property
    def days_left(self):
        return max(0, (self.expires_at - timezone.now()).days)