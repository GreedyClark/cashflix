from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.htmx import toast_response
from apps.money.forms import format_amount, month_start, next_month
from apps.money.icon_catalog import choices
from apps.recurring.dates import add_months

from .forms import LimitForm
from .models import Limit
from .summary import BudgetMonth, SpendingHistory

CHANGED = ["limitsChanged", "closeModal"]


def budget(request):
    today = timezone.localdate()
    month = month_start(request.GET.get("month"))
    data = BudgetMonth(request.household, month, today)
    limits = data.limits()
    context = {
        "month": month,
        "previous_month": add_months(month, -1).strftime("%Y-%m"),
        "next_month": next_month(month).strftime("%Y-%m") if month < today.replace(day=1) else None,
        "is_current": data.is_current,
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
        history = SpendingHistory(request.household, timezone.localdate().replace(day=1))
        hints = history.for_limit(int(category), int(member) if member and member.isdigit() else None)
    return render(request, "budgets/_hints.html", {"hints": hints})


def limit_amount(request):
    try:
        value = format_amount(Decimal(request.GET.get("value", "")))
    except InvalidOperation:
        value = ""
    form = LimitForm(household=request.household, initial={"amount": value})
    return render(request, "budgets/_amount_input.html", {"form": form})
