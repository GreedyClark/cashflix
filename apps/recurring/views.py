import datetime
from decimal import Decimal

from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.budgets.summary import month_end
from apps.core.htmx import toast_response
from apps.money.models import Transaction
from apps.recurring.dates import add_months

from .forms import PayForm, PaymentForm
from .services import in_base, monthly_amount, occurrences, pay_now

CHANGED = ("paymentsChanged", "closeModal")
PAID = ("paymentsChanged", "transactionsChanged", "accountsChanged", "closeModal")
ZERO = Decimal("0")


def group_for(payment, today, week_end, end_of_month):
    if not payment.is_active:
        return "paused"
    if payment.next_date < today:
        return "overdue"
    if payment.next_date <= week_end:
        return "week"
    if payment.next_date <= end_of_month:
        return "month"
    return "later"


def average_income(household, today):
    first = add_months(today.replace(day=1), -3)
    last = today.replace(day=1) - datetime.timedelta(days=1)
    return household.transactions.incomes().between(first, last).total_base() / 3


def payment_list(request):
    household = request.household
    today = timezone.localdate()
    week_end = today + datetime.timedelta(days=7)
    end_of_month = month_end(today)
    payments = household.recurring_payments.select_related("account", "category", "member__user", "household")

    groups = {key: [] for key in ("overdue", "week", "month", "later", "paused")}
    monthly = ZERO
    left_this_month = ZERO
    for payment in payments:
        payment.days_left = (payment.next_date - today).days
        groups[group_for(payment, today, week_end, end_of_month)].append(payment)
        if not payment.is_active or payment.type != Transaction.Type.EXPENSE:
            continue
        monthly += monthly_amount(payment, today) or ZERO
        upcoming = occurrences(payment, today, end_of_month)
        left_this_month += (in_base(payment, payment.amount, today) or ZERO) * len(upcoming)

    income = average_income(household, today)
    share = round(monthly / income * 100) if income else None
    titles = {
        "overdue": _("Пропущені"),
        "week": _("Найближчі 7 днів"),
        "month": _("До кінця місяця"),
        "later": _("Пізніше"),
        "paused": _("На паузі"),
    }
    context = {
        "groups": [{"key": key, "title": titles[key], "items": items} for key, items in groups.items() if items],
        "monthly": monthly,
        "left_this_month": left_this_month,
        "income": income,
        "share": share,
        "share_bar": min(100, share or 0),
        "count": sum(1 for p in payments if p.is_active),
        "today": today,
    }
    template = "recurring/_payment_list.html" if request.headers.get("HX-Request") else "recurring/payment_list.html"
    return render(request, template, context)


def payment_form(request, payment=None):
    form = PaymentForm(request.POST or None, instance=payment, household=request.household, membership=request.membership)
    if request.method == "POST" and form.is_valid():
        form.save()
        message = _("Платіж додано") if payment is None else _("Зміни збережено")
        return toast_response(request, message, events=CHANGED)
    context = {"form": form, "payment": payment, "notify_url": reverse("notifications:settings")}
    return render(request, "recurring/_payment_form.html", context)


def payment_create(request):
    return payment_form(request)


def payment_edit(request, pk):
    return payment_form(request, get_object_or_404(request.household.recurring_payments, pk=pk))


def payment_pay(request, pk):
    payment = get_object_or_404(request.household.recurring_payments, pk=pk, is_active=True)
    form = PayForm(request.POST or None, payment=payment)
    if request.method == "POST" and form.is_valid():
        pay_now(payment, form.cleaned_data["amount"], form.cleaned_data["date"])
        return toast_response(request, _("Операцію додано, наступний платіж перенесено"), events=PAID)
    return render(request, "recurring/_payment_pay.html", {"form": form, "payment": payment})


@require_POST
def payment_toggle(request, pk):
    payment = get_object_or_404(request.household.recurring_payments, pk=pk)
    payment.is_active = not payment.is_active
    if payment.is_active and payment.next_date < timezone.localdate():
        payment.next_date = timezone.localdate()
    payment.save(update_fields=["is_active", "next_date"])
    message = _("Платіж відновлено") if payment.is_active else _("Платіж на паузі")
    return toast_response(request, message, events=CHANGED)


@require_POST
def payment_delete(request, pk):
    get_object_or_404(request.household.recurring_payments, pk=pk).delete()
    return toast_response(request, _("Платіж видалено, створені операції лишилися"), events=CHANGED)
