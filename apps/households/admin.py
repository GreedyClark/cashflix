from django.contrib import admin

from .models import Household, Membership


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ["name", "base_currency", "members_count", "created_at"]
    search_fields = ["name"]
    inlines = [MembershipInline]

    @admin.display(description="Учасників")
    def members_count(self, obj):
        return obj.memberships.count()