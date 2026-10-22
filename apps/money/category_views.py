from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.htmx import toast_response

from .category_forms import CategoryForm, MergeForm
from .icon_catalog import choices
from .models import Category, Transaction
from .services import merge_categories

CHANGED = ("categoriesChanged", "closeModal")


def category_stats(household, month):
    rows = (
        Transaction.objects.filter(household=household, category__isnull=False)
        .order_by()
        .values("category")
        .annotate(count=Count("id"), month=Sum("amount_base", filter=Q(date__gte=month)))
    )
    return {row["category"]: row for row in rows}


def category_list(request):
    household = request.household
    archived = request.GET.get("archived") == "1"
    stats = category_stats(household, timezone.localdate().replace(day=1))
    categories = (
        household.categories.filter(is_archived=archived)
        .annotate(limit_count=Count("limits", distinct=True), payment_count=Count("recurring_payments", distinct=True))
    )
    groups = {Category.Kind.EXPENSE: [], Category.Kind.INCOME: []}
    for category in categories:
        row = stats.get(category.pk, {})
        category.count = row.get("count", 0)
        category.month_total = row.get("month") or 0
        category.can_delete = not category.count and not category.payment_count
        groups[category.kind].append(category)
    context = {
        "groups": [
            {"kind": Category.Kind.EXPENSE, "title": _("Витрати"), "items": groups[Category.Kind.EXPENSE]},
            {"kind": Category.Kind.INCOME, "title": _("Доходи"), "items": groups[Category.Kind.INCOME]},
        ],
        "archived": archived,
        "archived_count": household.categories.filter(is_archived=True).count(),
    }
    template = "money/_category_list.html" if request.headers.get("HX-Request") else "money/category_list.html"
    return render(request, template, context)


def category_form(request, category=None):
    kind = request.GET.get("kind") if category is None and request.GET.get("kind") in Category.Kind.values else None
    form = CategoryForm(request.POST or None, instance=category, household=request.household, kind=kind)
    if request.method == "POST" and form.is_valid():
        form.save()
        message = _("Категорію додано") if category is None else _("Зміни збережено")
        return toast_response(request, message, events=CHANGED)
    icons = choices(form["name"].value(), "", form["icon"].value())
    return render(request, "money/_category_form.html", {"form": form, "category": category, "icons": icons})


def category_create(request):
    return category_form(request)


def category_edit(request, pk):
    return category_form(request, get_object_or_404(request.household.categories, pk=pk))


@require_POST
def category_archive(request, pk):
    category = get_object_or_404(request.household.categories, pk=pk)
    category.is_archived = not category.is_archived
    category.save(update_fields=["is_archived"])
    message = _("Категорію сховано в архів") if category.is_archived else _("Категорію повернуто")
    return toast_response(request, message, events=CHANGED)


@require_POST
def category_delete(request, pk):
    category = get_object_or_404(request.household.categories, pk=pk)
    if category.transactions.exists() or category.recurring_payments.exists():
        return toast_response(request, _("У категорії є операції, її можна лише сховати"))
    category.delete()
    return toast_response(request, _("Категорію видалено"), events=CHANGED)


def category_merge(request, pk):
    source = get_object_or_404(request.household.categories, pk=pk)
    form = MergeForm(request.POST or None, source=source)
    if request.method == "POST" and form.is_valid():
        target = form.cleaned_data["target"]
        merge_categories(source, target)
        return toast_response(request, _("Об'єднано з «%(name)s»") % {"name": target.name}, events=CHANGED)
    context = {"form": form, "source": source, "count": source.transactions.count()}
    return render(request, "money/_category_merge.html", context)


def icon_grid(request):
    picked = "" if request.GET.get("trigger") == "name" else request.GET.get("icon", "")
    icons = choices(request.GET.get("name"), request.GET.get("icon_query"), picked)
    return render(request, "money/_icon_grid.html", {"icons": icons})
