from django.contrib import admin

from .models import Household, Invitation, Membership


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


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ["household", "created_by", "created_at", "expires_at", "is_revoked", "accepted_by"]
    list_filter = ["household", "is_revoked"]
    readonly_fields = ["token", "created_at", "accepted_by", "accepted_at"]