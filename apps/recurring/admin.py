from django.contrib import admin

from .models import RecurringPayment


@admin.register(RecurringPayment)
class RecurringPaymentAdmin(admin.ModelAdmin):
    list_display = ["title", "amount", "period", "next_date", "account", "category", "is_active"]
    list_filter = ["household", "period", "is_active"]
    list_editable = ["is_active"]
    search_fields = ["title"]