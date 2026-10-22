from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from .models import ExchangeRate, Transaction
from .rates import RateNotFound, convert_rate, latest_rate

ZERO = Decimal("0")
CENT = Decimal("0.01")
KIND_ORDER = ["card", "cash", "savings", "investment"]


@dataclass
class Investment:
    invested: Decimal
    value: Decimal
    payouts: Decimal
    valued_on: object

    @property
    def profit(self):
        return self.value - self.invested

    @property
    def percent(self):
        return round(self.profit / self.invested * 100, 1) if self.invested else None


def total(queryset, field):
    return queryset.aggregate(total=Coalesce(Sum(field), ZERO))["total"]


def investment_for(account):
    incoming = total(Transaction.objects.filter(to_account=account, type=Transaction.Type.TRANSFER), "to_amount")
    outgoing = total(account.transactions.filter(type=Transaction.Type.TRANSFER), "amount")
    payouts = total(account.transactions.incomes(), "amount")
    valuation = account.valuations.first()
    return Investment(
        invested=account.opening_balance + incoming - outgoing,
        value=valuation.value if valuation else account.balance,
        payouts=payouts,
        valued_on=valuation.date if valuation else None,
    )


def month_flow(account, start, end):
    moved_in = Q(account=account, type=Transaction.Type.INCOME) | Q(to_account=account, type=Transaction.Type.TRANSFER)
    moved_out = Q(account=account, type__in=[Transaction.Type.EXPENSE, Transaction.Type.TRANSFER])
    period = Transaction.objects.filter(date__gte=start, date__lte=end)
    incoming = period.filter(moved_in)
    received = total(incoming.filter(account=account), "amount") + total(incoming.exclude(account=account), "to_amount")
    return received, total(period.filter(moved_out), "amount")


def load_accounts(household, today, archived=False):
    accounts = household.accounts.filter(is_archived=archived).with_balance().select_related("owner__user")
    accounts = sorted(accounts, key=lambda account: KIND_ORDER.index(account.kind))
    for account in accounts:
        account.investment = investment_for(account) if account.is_investment else None
        account.value = account.investment.value if account.investment else account.balance
        try:
            account.rate = convert_rate(account.currency, household.base_currency, today)
            account.converted = (account.value * account.rate).quantize(CENT)
        except RateNotFound:
            account.rate = None
            account.converted = None
    return accounts


def rate_changes(today, currencies=("USD", "EUR")):
    rows = []
    for currency in currencies:
        latest = ExchangeRate.objects.filter(currency=currency, date__lte=today).first()
        if not latest:
            continue
        before = latest_rate(currency, latest.date - timedelta(days=1))
        rows.append({
            "currency": currency,
            "rate": latest.rate,
            "date": latest.date,
            "change": latest.rate - before if before else None,
        })
    return rows
