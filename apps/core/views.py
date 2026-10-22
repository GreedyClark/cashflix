from django.shortcuts import render

from .dashboard import Overview


def home(request):
    household = request.household
    member = household.memberships.active().filter(pk=request.GET.get("member") or None).first()
    overview = Overview(household, member=member)

    spending = overview.spending()
    half_year = overview.half_year()
    categories = overview.categories()
    context = {
        "member": member,
        "members": household.memberships.active().select_related("user"),
        "today": overview.today,
        "days_in_month": overview.days_in_month,
        "kpis": overview.kpis(),
        "spending": spending,
        "half_year": half_year,
        "categories": categories,
        "limits": overview.limits(),
        "pace": overview.pace(),
        "recent": overview.recent(),
        "accounts": overview.accounts,
        "goals": overview.goals(),
        "chart_data": overview.chart_data(spending, half_year, categories),
    }
    template = "core/_overview.html" if request.headers.get("HX-Request") else "core/home.html"
    return render(request, template, context)
