import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from apps.households.models import Household, Membership
from apps.households.services import add_member, create_household

User = get_user_model()


@pytest.fixture
def yura(db):
    return User.objects.create_user(email="yura@example.com", password="pass12345")


@pytest.fixture
def olya(db):
    return User.objects.create_user(email="olya@example.com", password="pass12345")


def test_create_household_makes_owner(yura):
    household = create_household(yura, "Дім")

    membership = household.memberships.get()
    assert membership.user == yura
    assert membership.is_owner
    assert membership.color_slot == 1
    assert household.base_currency == "UAH"


def test_second_member_gets_next_color(yura, olya):
    household = create_household(yura, "Дім")
    membership = add_member(household, olya)

    assert membership.role == Membership.Role.MEMBER
    assert membership.color_slot == 2


def test_add_member_twice_returns_same_membership(yura, olya):
    household = create_household(yura, "Дім")

    first = add_member(household, olya)
    second = add_member(household, olya)

    assert first.pk == second.pk
    assert household.memberships.count() == 2


def test_duplicate_membership_is_rejected(yura):
    household = create_household(yura, "Дім")

    with pytest.raises(IntegrityError):
        Membership.objects.create(household=household, user=yura)


def test_for_user_returns_only_own_households(yura, olya):
    home = create_household(yura, "Дім")
    create_household(olya, "Інше господарство")

    assert list(Household.objects.for_user(yura)) == [home]