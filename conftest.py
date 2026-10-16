import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.households.services import add_member, create_household
from apps.money.models import Account, Category, ExchangeRate

User = get_user_model()


@pytest.fixture
def home(db):
    yura = User.objects.create_user(email="yura@example.com", password="pass12345")
    return create_household(yura, "Дім")


@pytest.fixture
def yura(home):
    return home.memberships.get(user__email="yura@example.com")


@pytest.fixture
def olya(home):
    user = User.objects.create_user(email="olya@example.com", password="pass12345")
    return add_member(home, user)


@pytest.fixture
def mono(home, yura):
    return Account.objects.create(household=home, name="Монобанк", owner=yura, opening_balance=Decimal("1000"))


@pytest.fixture
def cash(home):
    return Account.objects.create(household=home, name="Готівка", kind=Account.Kind.CASH)


@pytest.fixture
def usd_account(home):
    return Account.objects.create(household=home, name="Доларовий", currency="USD")


@pytest.fixture
def food(home):
    return home.categories.get(kind=Category.Kind.EXPENSE, name="Продукти")


@pytest.fixture
def home_subs(home):
    return home.categories.get(kind=Category.Kind.EXPENSE, name="Підписки")


@pytest.fixture
def salary(home):
    return home.categories.get(kind=Category.Kind.INCOME, name="Зарплата")


@pytest.fixture
def usd_rate(db):
    return ExchangeRate.objects.create(currency="USD", date=datetime.date(2026, 10, 1), rate=Decimal("41.32"))