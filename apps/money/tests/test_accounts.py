import datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.households.services import create_household
from apps.money import nbu
from apps.money.accounts import investment_for, load_accounts
from apps.money.models import Account, AccountValuation, ExchangeRate, Transaction
from apps.money.rates import uah_rate

DAY = datetime.date(2026, 10, 15)


@pytest.fixture
def yura_client(client, yura):
    client.force_login(yura.user)
    return client


@pytest.fixture
def fund(home, yura):
    return Account.objects.create(
        household=home, name="Фонд нерухомості", kind="investment", investment_type="Фонд нерухомості", yield_mode="market", owner=yura,
        opening_balance=Decimal("20000"),
    )


def test_investment_profit_and_payouts(home, mono, fund, salary):
    Transaction.objects.create(household=home, type="transfer", account=mono, to_account=fund, amount=Decimal("3000"), title="Поповнення", date=DAY)
    Transaction.objects.create(household=home, type="income", account=fund, category=salary, amount=Decimal("500"), title="Виплата", date=DAY)
    AccountValuation.objects.create(account=fund, date=DAY, value=Decimal("24000"))

    investment = investment_for(Account.objects.with_balance().get(pk=fund.pk))

    assert investment.invested == Decimal("23000")
    assert investment.value == Decimal("24000")
    assert investment.profit == Decimal("1000")
    assert investment.percent == Decimal("4.3")
    assert investment.payouts == Decimal("500")


def test_investment_counts_at_value_in_totals(home, fund):
    AccountValuation.objects.create(account=fund, date=DAY, value=Decimal("25000"))

    account = load_accounts(home, DAY)[0]

    assert account.converted == Decimal("25000")


def test_page_shows_only_own_accounts(yura_client, mono, user):
    stranger = create_household(user, "Чужий дім")
    foreign = Account.objects.create(household=stranger, name="Чужа картка")

    response = yura_client.get(reverse("money:accounts"))

    assert response.status_code == 200
    assert [a.name for a in response.context["accounts"]] == ["Монобанк"]
    assert yura_client.get(reverse("money:account_edit", args=[foreign.pk])).status_code == 404


def test_create_account_with_comma_balance(yura_client, home, yura):
    response = yura_client.post(reverse("money:account_create"), {
        "name": "ПриватБанк", "kind": "card", "currency": "UAH", "owner": yura.pk, "opening_balance": "1 250,50",
    })

    assert response["HX-Reswap"] == "none"
    account = home.accounts.get(name="ПриватБанк")
    assert account.opening_balance == Decimal("1250.50")
    assert account.investment_type == ""


def bonds_account(home, payout, **fields):
    return Account.objects.create(
        household=home, name="ОВДП", kind="investment", investment_type="ОВДП", yield_mode="fixed",
        annual_rate=Decimal("16"), starts_on=datetime.date(2026, 1, 1), ends_on=datetime.date(2027, 1, 1),
        payout=payout, opening_balance=Decimal("36500"), **fields,
    )


def test_fixed_interest_accrues_by_day(home):
    account = bonds_account(home, "end")

    investment = investment_for(Account.objects.with_balance().get(pk=account.pk), datetime.date(2026, 4, 11))

    assert investment.accrued == Decimal("1600.00")
    assert investment.value == Decimal("38100.00")
    assert investment.expected == Decimal("42340.00")
    assert investment.days_left == 265


def test_fixed_interest_counts_each_deposit_from_its_date(home, mono):
    account = bonds_account(home, "end")
    Transaction.objects.create(
        household=home, type="transfer", account=mono, to_account=account, amount=Decimal("36500"), title="Поповнення",
        date=datetime.date(2026, 3, 1),
    )

    investment = investment_for(Account.objects.with_balance().get(pk=account.pk), datetime.date(2026, 3, 11))

    assert investment.invested == Decimal("73000")
    assert investment.accrued == Decimal("1264.00")


def test_monthly_payout_keeps_value_at_invested(home):
    account = bonds_account(home, "monthly")

    investment = investment_for(Account.objects.with_balance().get(pk=account.pk), datetime.date(2026, 4, 10))

    assert investment.value == Decimal("36500")
    assert investment.monthly == Decimal("486.67")
    assert investment.expected is None


def test_capitalization_grows_faster(home):
    simple = investment_for(Account.objects.with_balance().get(pk=bonds_account(home, "end").pk), datetime.date(2027, 1, 1))
    compound = investment_for(Account.objects.with_balance().get(pk=bonds_account(home, "capitalize").pk), datetime.date(2027, 1, 1))

    assert compound.accrued > simple.accrued
    assert compound.accrued == compound.expected - compound.invested


def test_create_fixed_investment(yura_client, home):
    response = yura_client.post(reverse("money:account_create"), {
        "name": "Депозит", "kind": "investment", "investment_type": "Депозит", "yield_mode": "fixed",
        "annual_rate": "14,5", "starts_on": "2026-10-01", "ends_on": "2027-04-01", "payout": "monthly",
        "currency": "UAH", "owner": "", "opening_balance": "20 000",
    })

    assert response["HX-Reswap"] == "none"
    account = home.accounts.get(name="Депозит")
    assert account.annual_rate == Decimal("14.5")
    assert account.payout == "monthly"


def test_fixed_investment_needs_rate_and_valid_dates(yura_client, home):
    response = yura_client.post(reverse("money:account_create"), {
        "name": "Депозит", "kind": "investment", "yield_mode": "fixed",
        "starts_on": "2026-10-01", "ends_on": "2026-09-01", "currency": "UAH", "owner": "",
    })

    form = response.context["form"]
    assert set(form.errors) == {"annual_rate", "ends_on"}
    assert not home.accounts.filter(name="Депозит").exists()


def test_market_investment_drops_fixed_fields(yura_client, home):
    yura_client.post(reverse("money:account_create"), {
        "name": "Акції", "kind": "investment", "investment_type": "Акції", "yield_mode": "market",
        "annual_rate": "10", "starts_on": "2026-10-01", "currency": "UAH", "owner": "",
    })

    account = home.accounts.get(name="Акції")
    assert account.annual_rate is None
    assert account.starts_on is None
    assert account.investment_type == "Акції"


def test_archive_and_restore(yura_client, mono):
    yura_client.post(reverse("money:account_archive", args=[mono.pk]))
    mono.refresh_from_db()
    assert mono.is_archived

    yura_client.post(reverse("money:account_archive", args=[mono.pk]))
    mono.refresh_from_db()
    assert not mono.is_archived


def test_valuation_for_same_day_is_replaced(yura_client, fund):
    url = reverse("money:valuation_create", args=[fund.pk])
    yura_client.post(url, {"value": "21000", "date": "2026-10-15"})
    yura_client.post(url, {"value": "21 500", "date": "2026-10-15"})

    assert list(fund.valuations.values_list("value", flat=True)) == [Decimal("21500")]


def test_valuation_only_for_investments(yura_client, mono):
    assert yura_client.get(reverse("money:valuation_create", args=[mono.pk])).status_code == 404


def test_update_rates_command(db, monkeypatch):
    monkeypatch.setattr(nbu, "fetch", lambda on_date: {"USD": Decimal("41.5"), "EUR": Decimal("45.1")})

    call_command("update_rates", days=2)

    assert ExchangeRate.objects.count() == 4


def test_missing_rate_is_downloaded(db, monkeypatch):
    monkeypatch.setattr(nbu, "fetch", lambda on_date: {"USD": Decimal("41.5")})

    assert uah_rate("USD", DAY) == Decimal("41.5")
    assert ExchangeRate.objects.filter(currency="USD", date=DAY).exists()


def test_transfer_between_currencies_with_received_amount(yura_client, home, mono, usd_account, usd_rate):
    yura_client.post(reverse("money:transaction_create"), {
        "type": "transfer", "amount": "4200", "title": "Купівля доларів", "when": "other", "date": "2026-10-15",
        "account": mono.pk, "to_account": usd_account.pk, "to_amount": "100", "member": "",
    })

    tx = home.transactions.get()
    assert tx.to_amount == Decimal("100")
    assert Account.objects.with_balance().get(pk=usd_account.pk).balance == Decimal("100")


def test_transfer_form_prefilled_from_link(yura_client, mono):
    response = yura_client.get(reverse("money:transaction_create"), {"type": "transfer", "account": mono.pk})
    form = response.context["form"]

    assert form["type"].value() == "transfer"
    assert str(form["account"].value()) == str(mono.pk)


def test_delete_only_empty_account(yura_client, home, mono, cash, food):
    Transaction.objects.create(household=home, account=mono, category=food, amount=Decimal("10"), title="x", date=DAY)

    yura_client.post(reverse("money:account_delete", args=[mono.pk]))
    yura_client.post(reverse("money:account_delete", args=[cash.pk]))

    assert home.accounts.filter(pk=mono.pk).exists()
    assert not home.accounts.filter(pk=cash.pk).exists()


def test_transfer_target_cannot_be_deleted(yura_client, home, mono, cash):
    Transaction.objects.create(household=home, type="transfer", account=mono, to_account=cash, amount=Decimal("10"), title="x", date=DAY)

    yura_client.post(reverse("money:account_delete", args=[cash.pk]))

    assert home.accounts.filter(pk=cash.pk).exists()


def test_page_marks_deletable_accounts(yura_client, home, mono, cash, food):
    Transaction.objects.create(household=home, account=mono, category=food, amount=Decimal("10"), title="x", date=DAY)

    accounts = {a.name: a.can_delete for a in yura_client.get(reverse("money:accounts")).context["accounts"]}

    assert accounts == {"Монобанк": False, "Готівка": True}


def test_foreign_account_delete_is_404(yura_client, user):
    stranger = create_household(user, "Чужий дім")
    foreign = Account.objects.create(household=stranger, name="Чужа")

    assert yura_client.post(reverse("money:account_delete", args=[foreign.pk])).status_code == 404
