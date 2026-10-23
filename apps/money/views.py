import calendar
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.htmx import toast_response

from .accounts import load_accounts, month_flow, rate_changes
from .categorize import remember
from .export import build_workbook, file_name
from .forms import AccountForm, TransactionFilterForm, TransactionForm, ValuationForm, next_month
from .models import Account
from .services import restore, snapshot

UNDO_KEY = "undo_transaction"


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
    filter_names = ("q", "type", "category", "member", "account", "day", "review")
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
        "review_count": household.transactions.filter(Q(needs_review=True) | Q(duplicate_of__isnull=False)).count(),
        "refresh_filters": bool(request.headers.get("HX-Request")),
    }
    template = "money/_transaction_results.html" if request.headers.get("HX-Request") else "money/transaction_list.html"
    return render(request, template, context)


def transaction_export(request):
    household = request.household
    data = request.GET.copy()
    if not data.get("month"):
        data["month"] = timezone.localdate().strftime("%Y-%m")
    form = TransactionFilterForm(data, household=household)
    form.is_valid()
    base = household.transactions.select_related("category", "account", "to_account", "member__user")
    transactions = form.filter(base).order_by("date", "created_at")
    content = build_workbook(household, transactions, timezone.localdate())
    response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{file_name(form.cleaned_data["month"])}"'
    return response


CHANGED = ("transactionsChanged", "accountsChanged", "closeModal")


def transaction_form(request, transaction=None, initial=None):
    form = TransactionForm(
        request.POST or None,
        instance=transaction,
        initial=initial,
        household=request.household,
        membership=request.membership,
    )
    if request.method == "POST" and form.is_valid():
        is_new = form.instance.pk is None
        if is_new:
            form.instance.created_by = request.user
        form.instance.needs_review = False
        tx = form.save()
        remember(tx)
        return toast_response(request, _("Операцію додано") if is_new else _("Зміни збережено"), events=CHANGED)
    return render(request, "money/_transaction_form.html", {"form": form, "transaction": transaction})


def transaction_create(request):
    initial = {name: request.GET[name] for name in ("type", "account", "to_account") if request.GET.get(name)}
    return transaction_form(request, initial=initial)


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
def transaction_not_duplicate(request, pk):
    transaction = get_object_or_404(request.household.transactions, pk=pk)
    transaction.duplicate_of = None
    transaction.save(update_fields=["duplicate_of"])
    return toast_response(request, _("Позначено як окрему операцію"), events=CHANGED)


@require_POST
def transaction_undo(request):
    data = request.session.pop(UNDO_KEY, None)
    if data:
        restore(request.household, data)
    return toast_response(request, _("Операцію повернуто"), events=CHANGED)


def account_list(request):
    household = request.household
    today = timezone.localdate()
    archived = request.GET.get("archived") == "1"
    accounts = load_accounts(household, today, archived=archived)

    month_start = today.replace(day=1)
    used = used_account_ids(household)
    for index, account in enumerate(accounts):
        account.tone = tone_for(index)
        account.can_delete = account.pk not in used
        account.received, account.spent = month_flow(account, month_start, today)

    active = accounts if not archived else []
    total = sum((a.converted for a in active if a.converted is not None), Decimal("0"))
    shares = [
        {"account": a, "percent": round(a.converted / total * 100) if total else 0}
        for a in active
        if a.converted and a.converted > 0
    ]
    context = {
        "accounts": accounts,
        "archived": archived,
        "archived_count": household.accounts.filter(is_archived=True).count(),
        "total": total,
        "shares": shares,
        "rates": rate_changes(today),
        "today": today,
    }
    template = "money/_account_list.html" if request.headers.get("HX-Request") else "money/account_list.html"
    return render(request, template, context)


def tone_for(index):
    return ACCOUNT_TONES[index % len(ACCOUNT_TONES)]


ACCOUNT_TONES = [1, 2, 3, 5, 7, 4, 6]
ACCOUNTS_CHANGED = ("accountsChanged", "closeModal")


def account_form(request, account=None):
    form = AccountForm(request.POST or None, instance=account, household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        message = _("Рахунок додано") if account is None else _("Зміни збережено")
        return toast_response(request, message, events=ACCOUNTS_CHANGED)
    return render(request, "money/_account_form.html", {"form": form, "account": account})


def account_create(request):
    return account_form(request)


def account_edit(request, pk):
    return account_form(request, get_object_or_404(request.household.accounts, pk=pk))


@require_POST
def account_archive(request, pk):
    account = get_object_or_404(request.household.accounts, pk=pk)
    account.is_archived = not account.is_archived
    account.save(update_fields=["is_archived"])
    message = _("Рахунок перенесено в архів") if account.is_archived else _("Рахунок повернуто з архіву")
    return toast_response(request, message, events=ACCOUNTS_CHANGED)


def used_account_ids(household):
    used = set(household.transactions.values_list("account_id", flat=True))
    used |= set(household.transactions.exclude(to_account=None).values_list("to_account_id", flat=True))
    used |= set(household.recurring_payments.values_list("account_id", flat=True))
    return used


@require_POST
def account_delete(request, pk):
    account = get_object_or_404(request.household.accounts, pk=pk)
    if account.pk in used_account_ids(request.household):
        return toast_response(request, _("По рахунку є операції або регулярні платежі, його можна лише сховати в архів"))
    account.delete()
    return toast_response(request, _("Рахунок видалено"), events=ACCOUNTS_CHANGED)


def valuation_create(request, pk):
    account = get_object_or_404(request.household.accounts, pk=pk, kind=Account.Kind.INVESTMENT)
    form = ValuationForm(request.POST or None, account=account)
    if request.method == "POST" and form.is_valid():
        form.save()
        return toast_response(request, _("Вартість оновлено"), events=ACCOUNTS_CHANGED)
    return render(request, "money/_valuation_form.html", {"form": form, "account": account})
