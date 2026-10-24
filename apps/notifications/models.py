import datetime

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class NotifySettings(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notify_settings")
    remind_at = models.TimeField(_("о котрій нагадувати"), default=datetime.time(9, 0))
    telegram = models.BooleanField(_("нагадувати в Telegram"), default=True)
    last_sent_on = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = _("налаштування сповіщень")
        verbose_name_plural = _("налаштування сповіщень")

    def __str__(self):
        return f"{self.user} · {self.remind_at:%H:%M}"

    @classmethod
    def of(cls, user):
        found, _created = cls.objects.get_or_create(user=user)
        return found


class PushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.CharField(max_length=600, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    label = models.CharField(_("пристрій"), max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("push-підписка")
        verbose_name_plural = _("push-підписки")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} · {self.label}"

    def info(self):
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}
