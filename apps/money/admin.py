from django.contrib import admin

from .models import Account, Category, ExchangeRate, Transaction


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["name", "household", "kind", "currency", "owner", "balance", "is_archived"]
    list_filter = ["household", "kind", "currency", "is_archived"]
    search_fields = ["name"]

    def get_queryset(self, request):
        return super().get_queryset(request).with_balance().select_related("household", "owner__user")

    @admin.display(description="Баланс")
    def balance(self, obj):
        return obj.balance


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "household", "kind", "icon", "color_slot", "order", "is_archived"]
    list_filter = ["household", "kind", "is_archived"]
    list_editable = ["order"]
    search_fields = ["name"]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ["date", "title", "type", "amount", "currency", "amount_base", "category", "account", "member"]
    list_filter = ["household", "type", "account", "category", "source"]
    search_fields = ["title", "note"]
    date_hierarchy = "date"
    readonly_fields = ["currency", "rate", "amount_base", "created_by", "created_at"]
    list_select_related = ["category", "account", "member__user"]

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ["date", "currency", "rate"]
    list_filter = ["currency"]
    date_hierarchy = "date"