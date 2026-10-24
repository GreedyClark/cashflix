from django.contrib import admin

from .models import NotifySettings, PushSubscription


@admin.register(NotifySettings)
class NotifySettingsAdmin(admin.ModelAdmin):
    list_display = ["user", "remind_at", "telegram", "last_sent_on"]


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "label", "created_at"]
    readonly_fields = ["user", "label", "created_at"]
    exclude = ["endpoint", "p256dh", "auth"]
