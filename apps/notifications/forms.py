from django import forms
from django.utils.translation import gettext_lazy as _

from .models import NotifySettings


class NotifyForm(forms.ModelForm):
    class Meta:
        model = NotifySettings
        fields = ["remind_at", "telegram"]
        widgets = {"remind_at": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}
        error_messages = {"remind_at": {"invalid": _("Вкажіть час, наприклад 09:00.")}}
