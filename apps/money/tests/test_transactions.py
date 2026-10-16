import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.households.services import create_household
from apps.money.models import Account, Transaction
from apps.money.rates import RateNotFound

OCT_14 = datetime.date(2026, 10, 14)


def make(home, **fields):
    fields.setdefault("date", OCT_14)
    fields.setdefault("title", "Операція")
    tx = Transaction(household=home, **fields)
    tx.full_clean()
    tx.save()
    return tx


def test_expense_in_uah_keeps_amount(home, mono, food, yura):
    tx = make(home, account=mono, category=food, member=yura, amount=Decimal("612.40"))

    assert tx.currency == "UAH"
    assert tx.rate == Decimal("1")
    assert tx.amount_base == Decimal("612.40")


def test_expense_in_usd_is_converted_with_latest_rate(home, usd_account, home_subs, usd_rate):
    tx = make(home, account=usd_account, category=home_subs, amount=Decimal("8.99"), title="Netflix")

    assert tx.currency == "USD"
    assert tx.rate == Decimal("41.32")
    assert tx.amount_base == Decimal("371.47")


def test_missing_rate_raises(home, usd_account, home_subs):
    with pytest.raises(RateNotFound):
        make(home, account=usd_account, category=home_subs, amount=Decimal("10"))


def test_category_must_match_type(home, mono, salary):
    with pytest.raises(ValidationError) as error:
        make(home, account=mono, category=salary, amount=Decimal("100"))

    assert "category" in error.value.message_dict


def test_expense_requires_category(home, mono):
    with pytest.raises(ValidationError) as error:
        make(home, account=mono, amount=Decimal("100"))

    assert "category" in error.value.message_dict


def test_transfer_to_same_account_is_rejected(home, mono):
    with pytest.raises(ValidationError) as error:
        make(home, type=Transaction.Type.TRANSFER, account=mono, to_account=mono, amount=Decimal("100"))

    assert "to_account" in error.value.message_dict


def test_cannot_use_account_of_another_household(home, food, yura):
    other = create_household(yura.user, "Чуже")
    foreign_account = Account.objects.create(household=other, name="Чужий рахунок")

    with pytest.raises(ValidationError) as error:
        make(home, account=foreign_account, category=food, amount=Decimal("100"))

    assert "account" in error.value.message_dict


def test_balance_counts_income_expense_and_transfers(home, mono, cash, food, salary):
    make(home, account=mono, category=food, amount=Decimal("200"))
    make(home, type=Transaction.Type.INCOME, account=mono, category=salary, amount=Decimal("500"))
    make(home, type=Transaction.Type.TRANSFER, account=mono, to_account=cash, amount=Decimal("300"))

    balances = dict(Account.objects.with_balance().values_list("name", "balance"))

    assert balances["Монобанк"] == Decimal("1000")
    assert balances["Готівка"] == Decimal("300")
    assert mono.get_balance() == Decimal("1000")


def test_transfer_between_currencies_converts_received_amount(home, mono, usd_account, usd_rate):
    tx = make(home, type=Transaction.Type.TRANSFER, account=mono, to_account=usd_account, amount=Decimal("4132"))

    assert tx.to_amount == Decimal("100.00")
    assert usd_account.get_balance() == Decimal("100.00")


def test_transfers_are_not_expenses(home, mono, cash, food):
    make(home, account=mono, category=food, amount=Decimal("250"))
    make(home, type=Transaction.Type.TRANSFER, account=mono, to_account=cash, amount=Decimal("1000"))

    assert home.transactions.expenses().total_base() == Decimal("250")