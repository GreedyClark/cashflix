from django.apps import AppConfig


class TwofactorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.twofactor"
    verbose_name = "Двофакторний вхід"

    def ready(self):
        from . import signals  # noqa: F401
