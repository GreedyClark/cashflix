from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class MoneyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.money"
    verbose_name = _("Гроші")