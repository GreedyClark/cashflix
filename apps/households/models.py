from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Currency(models.TextChoices):
    UAH = "UAH", _("Гривня")
    USD = "USD", _("Долар США")
    EUR = "EUR", _("Євро")


class HouseholdQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(memberships__user=user)


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
    def is_owner(self):
        return self.role == self.Role.OWNER

    @property
    def color_var(self):
        return f"--cat-{self.color_slot}"