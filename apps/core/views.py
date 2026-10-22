import hmac

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .daily import run_daily
from .demo import USERS

from .dashboard import Overview
from .insights import Insights


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
        "upcoming": overview.upcoming(),
        "insights": Insights(overview).all(),
        "chart_data": overview.chart_data(spending, half_year, categories),
    }
    template = "core/_overview.html" if request.headers.get("HX-Request") else "core/home.html"
    return render(request, template, context)


@login_not_required
@require_POST
def demo_login(request):
    if not settings.DEBUG:
        raise Http404
    user = get_user_model().objects.filter(email=USERS[0][0]).first()
    if user is None:
        messages.error(request, _("Демо ще немає. Запустіть python manage.py seed_demo."))
        return redirect("account_login")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("core:home")


@login_not_required
def health(request):
    return HttpResponse("ok", content_type="text/plain")


@login_not_required
def daily_task(request, secret):
    expected = settings.CRON_SECRET
    if not expected or not hmac.compare_digest(secret, expected):
        raise Http404
    return HttpResponse("\n".join(run_daily()), content_type="text/plain")
