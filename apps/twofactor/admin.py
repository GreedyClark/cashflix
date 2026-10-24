from django.contrib import admin

from .models import SecondFactor, TrustedDevice


@admin.register(SecondFactor)
class SecondFactorAdmin(admin.ModelAdmin):
    list_display = ["user", "method", "telegram_username", "updated_at"]
    fields = ["user", "method", "telegram_username"]
    readonly_fields = ["user", "telegram_username"]


@admin.register(TrustedDevice)
class TrustedDeviceAdmin(admin.ModelAdmin):
    list_display = ["user", "label", "created_at", "expires_at", "last_seen_at"]
    readonly_fields = ["user", "label", "created_at", "expires_at", "last_seen_at"]
    exclude = ["key_hash"]
