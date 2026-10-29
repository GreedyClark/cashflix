from decimal import Decimal

from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.htmx import toast_response
from apps.money.icon_catalog import choices
from apps.money.rates import RateNotFound

from .forms import ContributionForm, GoalForm
from .models import GoalContribution
from .services import goal_items, month_plan, remove_contribution

CHANGED = ("goalsChanged", "closeModal")
MOVED = ("goalsChanged", "accountsChanged", "transactionsChanged", "closeModal")


def goal_list(request):
    household = request.household
    archived = request.GET.get("archived") == "1"
    today = timezone.localdate()
    items = goal_items(household, today, archived=archived)
    base = household.base_currency
    in_base = [item for item in items if item["goal"].currency == base]
    context = {
        "items": items,
        "plan": None if archived else month_plan(household, today, items),
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


def contribution_form(request, goal, contribution=None):
    form = ContributionForm(request.POST or None, goal=goal, membership=request.membership, contribution=contribution)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except RateNotFound:
            form.add_error("amount", _("Немає курсу валюти на цю дату. Спробуйте пізніше."))
        else:
            if contribution:
                message = _("Внесок змінено")
            elif form.cleaned_data["direction"] == form.OUT:
                message = _("Записано, що взяли з цілі")
            else:
                message = _("Відкладено в ціль")
            return toast_response(request, message, events=MOVED)
    history = []
    if not goal.tracks_account and contribution is None:
        history = goal.contributions.select_related("goal__household", "member__user", "transaction__account", "transaction__to_account")[:8]
    context = {"form": form, "goal": goal, "contribution": contribution, "history": history, "currency": form.currency}
    return render(request, "goals/_contribution_form.html", context)


def contribution_create(request, pk):
    goal = get_object_or_404(request.household.goals.select_related("account", "household"), pk=pk)
    return contribution_form(request, goal)


def household_contribution(request, pk):
    return get_object_or_404(
        GoalContribution.objects.select_related("goal__account", "goal__household", "transaction"),
        pk=pk, goal__household=request.household, goal__account__isnull=True,
    )


def contribution_edit(request, pk):
    contribution = household_contribution(request, pk)
    return contribution_form(request, contribution.goal, contribution)


@require_POST
def contribution_delete(request, pk):
    remove_contribution(household_contribution(request, pk))
    return toast_response(request, _("Внесок видалено"), events=MOVED)
