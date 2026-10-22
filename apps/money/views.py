import calendar
from datetime import timedelta

from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from .forms import TransactionFilterForm, next_month


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
    }
    template = "money/_transaction_results.html" if request.headers.get("HX-Request") else "money/transaction_list.html"
    return render(request, template, context)