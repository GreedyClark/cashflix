from decimal import Decimal

from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.htmx import toast_response
from apps.money.icon_catalog import choices

from .forms import ContributionForm, GoalForm
from .services import goal_items

CHANGED = ("goalsChanged", "closeModal")


def goal_list(request):
    household = request.household
    archived = request.GET.get("archived") == "1"
    items = goal_items(household, timezone.localdate(), archived=archived)
    base = household.base_currency
    in_base = [item for item in items if item["goal"].currency == base]
    context = {
        "items": items,
        "archived": archived,
        "archived_count": household.goals.filter(is_archived=True).count(),
        "saved": sum((item["saved"] for item in in_base), Decimal("0")),
        "target": sum((item["goal"].target_amount for item in in_base), Decimal("0")),
        "monthly": sum((item["monthly"] for item in in_base), Decimal("0")),
        "done_count": sum(1 for item in items if item["done"]),
    }
    template = "goals/_goal_list.html" if request.headers.get("HX-Request") else "goals/goal_list.html"
    return render(request, template, context)


def goal_form(request, goal=None):
    form = GoalForm(request.POST or None, instance=goal, household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        message = _("Ціль додано") if goal is None else _("Зміни збережено")
        return toast_response(request, message, events=CHANGED)
    icons = choices(form["name"].value(), "", form["icon"].value())
    return render(request, "goals/_goal_form.html", {"form": form, "goal": goal, "icons": icons})


def goal_create(request):
    return goal_form(request)


def goal_edit(request, pk):
    return goal_form(request, get_object_or_404(request.household.goals, pk=pk))


@require_POST
def goal_archive(request, pk):
    goal = get_object_or_404(request.household.goals, pk=pk)
    goal.is_archived = not goal.is_archived
    goal.save(update_fields=["is_archived"])
    message = _("Ціль перенесено в архів") if goal.is_archived else _("Ціль повернуто")
    return toast_response(request, message, events=CHANGED)


@require_POST
def goal_delete(request, pk):
    get_object_or_404(request.household.goals, pk=pk).delete()
    return toast_response(request, _("Ціль видалено"), events=CHANGED)


def contribution_create(request, pk):
    goal = get_object_or_404(request.household.goals, pk=pk, account__isnull=True)
    form = ContributionForm(request.POST or None, goal=goal, membership=request.membership)
    if request.method == "POST" and form.is_valid():
        contribution = form.save()
        message = _("Внесок записано") if contribution.amount > 0 else _("Записано, що взяли з цілі")
        return toast_response(request, message, events=CHANGED)
    history = goal.contributions.select_related("member__user")[:5]
    return render(request, "goals/_contribution_form.html", {"form": form, "goal": goal, "history": history})
