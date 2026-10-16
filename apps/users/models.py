from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class User(AbstractUser):
    username = None
    email = models.EmailField(_("email"), unique=True)
    display_name = models.CharField(_("ім'я в застосунку"), max_length=50, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = _("користувач")
        verbose_name_plural = _("користувачі")

    def __str__(self):
        return self.name

    @property
    def name(self):
        return self.display_name or self.first_name or self.email.split("@")[0]

    @property
    def initial(self):
        return self.name[:1].upper()