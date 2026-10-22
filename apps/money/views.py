import calendar
from datetime import timedelta

from django.db.models import Sum
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.htmx import toast_response

from .forms import TransactionFilterForm, TransactionForm, next_month
from .services import restore, snapshot

UNDO_KEY = "undo_transaction"
CHANGED = ("transactionsChanged", "closeModal")


def daily_bars(month, spent_by_day, selected):
    today = timezone.localdate()
    days_in_month = calendar.monthrange(month.year, month.month)[1]
    highest = max(spent_by_day.values(), default=0)
    bars = []
    for number in range(1, days_in_month + 1):
        date = month.replace(day=number)
        amount = spent_by_day.get(date, 0)
        bars.append({
            "date": date,
            "day": number,
            "amount": amount,
            "height": max(4, round(amount / highest * 100)) if highest and amount else 0,
            "is_today": date == today,
            "is_future": date > today,
            "is_selected": date == selected,
        })
    return bars


def transaction_list(request):
    household = request.household
    data = request.GET.copy()
    if not data.get("month"):
        data["month"] = timezone.localdate().strftime("%Y-%m")
    form = TransactionFilterForm(data, household=household)
    form.is_valid()
    month = form.cleaned_data["month"]
    selected_day = form.selected_day()

    base = household.transactions.select_related("category", "account", "to_account", "member__user")
    month_transactions = form.filter(base, by_day=False)
    transactions = form.filter(base)

    spent_by_day = dict(
        month_transactions.expenses().order_by().values("date").annotate(total=Sum("amount_base")).values_list("date", "total")
    )

    days = []
    for tx in transactions:
        if not days or days[-1]["date"] != tx.date:
            days.append({"date": tx.date, "spent": spent_by_day.get(tx.date), "items": []})
        days[-1]["items"].append(tx)

    spent = transactions.expenses().total_base()
    earned = transactions.incomes().total_base()
    previous_month = (month - timedelta(days=1)).replace(day=1)
    following_month = next_month(month)
    filter_names = ("q", "type", "category", "member", "account", "day")
    context = {
        "form": form,
        "days": days,
        "month": month,
        "selected_day": selected_day,
        "bars": daily_bars(month, spent_by_day, selected_day),
        "previous_month": previous_month.strftime("%Y-%m"),
        "next_month": following_month.strftime("%Y-%m"),
        "has_next": following_month <= timezone.localdate(),
        "spent": spent,
        "earned": earned,
        "balance": earned - spent,
        "is_filtered": any(form.cleaned_data.get(name) for name in filter_names),
        "has_any": household.transactions.exists(),
        "refresh_filters": bool(request.headers.get("HX-Request")),
    }
    template = "money/_transaction_results.html" if request.headers.get("HX-Request") else "money/transaction_list.html"
    return render(request, template, context)


def transaction_form(request, transaction=None):
    form = TransactionForm(
        request.POST or None,
        instance=transaction,
        household=request.household,
        membership=request.membership,
    )
    if request.method == "POST" and form.is_valid():
        is_new = form.instance.pk is None
        if is_new:
            form.instance.created_by = request.user
        form.save()
        return toast_response(request, _("Операцію додано") if is_new else _("Зміни збережено"), events=CHANGED)
    return render(request, "money/_transaction_form.html", {"form": form, "transaction": transaction})


def transaction_create(request):
    return transaction_form(request)


def transaction_edit(request, pk):
    transaction = get_object_or_404(request.household.transactions.select_related("created_by"), pk=pk)
    return transaction_form(request, transaction)


def transaction_delete(request, pk):
    transaction = get_object_or_404(request.household.transactions, pk=pk)
    if request.method != "POST":
        return render(request, "money/_transaction_delete.html", {"transaction": transaction})

    request.session[UNDO_KEY] = snapshot(transaction)
    transaction.delete()
    return toast_response(request, _("Операцію видалено"), reverse("money:transaction_undo"), events=CHANGED)


@require_POST
def transaction_undo(request):
    data = request.session.pop(UNDO_KEY, None)
    if data:
        restore(request.household, data)
    return toast_response(request, _("Операцію повернуто"), events=CHANGED)