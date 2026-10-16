from django.contrib import admin

from .models import Goal, GoalContribution


class ContributionInline(admin.TabularInline):
    model = GoalContribution
    extra = 0


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ["name", "household", "target_amount", "saved", "deadline", "is_archived"]
    list_filter = ["household", "is_archived"]
    inlines = [ContributionInline]

    def get_queryset(self, request):
        return super().get_queryset(request).with_saved()

    @admin.display(description="Накопичено")
    def saved(self, obj):
        return obj.saved