from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.htmx import toast_response
from apps.money.forms import format_amount
from apps.money.icon_catalog import choices

from .forms import LimitForm
from .income import MonthIncome, whole
from .periods import Period
from .models import Limit
from .summary import BudgetMonth, SpendingHistory

CHANGED = ["limitsChanged", "closeModal"]


def budget(request):
    today = timezone.localdate()
    household = request.household
    period = Period.from_key(request.GET.get("month"), household.month_start_day, today)
    data = BudgetMonth(household, period, today)
    limits = data.limits()
    context = {
        "period": period,
        "previous_month": period.previous().key,
        "next_month": period.next().key if period.end < today else None,
        "is_current": data.is_current,
        "income": data.income,
        "people": list(data.income.people.values()),
        "next_income": data.next_income_date(),
        "has_percent": any(item["limit"].is_percent for item in limits),
        "limits": limits,
        "summary": data.summary(limits),
        "free": data.free_categories(limits),
    }
    template = "budgets/_budget.html" if request.headers.get("HX-Request") else "budgets/budget.html"
    return render(request, template, context)


def limit_form(request, limit=None):
    initial = {"category": request.GET.get("category")} if limit is None else None
    form = LimitForm(request.POST or None, instance=limit, household=request.household, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.save()
        message = _("Ліміт додано") if limit is None else _("Зміни збережено")
        return toast_response(request, message, events=CHANGED)
    category_form = form.category_form
    icons = choices(category_form["name"].value(), "", category_form["icon"].value())
    context = {"form": form, "limit": limit, "category_form": category_form, "icons": icons}
    return render(request, "budgets/_limit_form.html", context)


def limit_create(request):
    return limit_form(request)


def limit_edit(request, pk):
    return limit_form(request, get_object_or_404(Limit, household=request.household, pk=pk))


@require_POST
def limit_delete(request, pk):
    get_object_or_404(Limit, household=request.household, pk=pk).delete()
    return toast_response(request, _("Ліміт видалено"), events=CHANGED)


def limit_hints(request):
    category = request.GET.get("category")
    hints = None
    if category and category.isdigit():
        member = request.GET.get("member")
        history = SpendingHistory(request.household, request.household.period())
        hints = history.for_limit(int(category), int(member) if member and member.isdigit() else None)
    return render(request, "budgets/_hints.html", {"hints": hints})


def limit_amount(request):
    try:
        value = format_amount(Decimal(request.GET.get("value", "")))
    except InvalidOperation:
        value = ""
    form = LimitForm(household=request.household, initial={"amount": value})
    return render(request, "budgets/_amount_input.html", {"form": form})


def limit_preview(request):
    household = request.household
    try:
        percent = Decimal(request.GET.get("percent", "").replace(",", "."))
    except InvalidOperation:
        percent = None
    if percent is not None and not 0 < percent <= 100:
        percent = None
    member = request.GET.get("member")
    member_id = int(member) if member and member.isdigit() else None
    income = MonthIncome(household, household.period(), timezone.localdate())
    base = income.of(member_id)
    share = percent / 100 if percent else None
    context = {
        "percent": percent,
        "base": base,
        "now": whole(base.received * share) if share else None,
        "full": whole(base.total * share) if share else None,
    }
    category = request.GET.get("category")
    if category and category.isdigit():
        history = SpendingHistory(household, household.period())
        context["previous"] = history.for_limit(int(category), member_id).previous
    return render(request, "budgets/_percent_preview.html", context)
