from django.contrib import admin

from .models import Limit


@admin.register(Limit)
class LimitAdmin(admin.ModelAdmin):
    list_display = ["category", "member", "amount", "household"]
    list_filter = ["household"]
    list_select_related = ["category", "member__user", "household"]