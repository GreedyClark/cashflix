import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.households.services import (
    accept_invitation,
    create_household,
    create_invitation,
    month_spending,
    remove_member,
)
from apps.money.models import Transaction


@pytest.fixture
def guest_client(client, olya):
    client.force_login(olya.user)
    return client


def test_owner_removes_member_and_history_stays(client, home, yura, olya, mono):
    Transaction.objects.create(
        household=home, account=mono, member=olya, amount=Decimal("300"), date=datetime.date(2026, 10, 5), title="Кава"
    )
    client.force_login(yura.user)

    response = client.post(reverse("households:member_remove", args=[olya.pk]))

    assert response.status_code == 302
    olya.refresh_from_db()
    assert olya.left_at is not None
    summary = month_spending(home, today=datetime.date(2026, 10, 20))
    assert summary["memberships"] == [yura]
    assert summary["former_members"] == [olya]
    assert summary["segments"][0]["amount"] == Decimal("300")


def test_removed_member_loses_access(guest_client, olya):
    remove_member(olya)

    response = guest_client.get(reverse("households:members"))

    assert response.status_code == 302
    assert response.url == reverse("households:onboarding")


def test_member_cannot_remove_others(guest_client, yura, olya, django_user_model):
    third = django_user_model.objects.create_user(email="x@gmail.com", password="x")
    accept_invitation(create_invitation(yura.household, yura.user), third)
    other = yura.household.memberships.get(user=third)

    response = guest_client.post(reverse("households:member_remove", args=[other.pk]))

    assert response.status_code == 403
    other.refresh_from_db()
    assert other.left_at is None


def test_owner_cannot_be_removed(client, yura):
    client.force_login(yura.user)

    response = client.post(reverse("households:member_remove", args=[yura.pk]))

    assert response.status_code == 403


def test_member_leaves_household(guest_client, olya):
    response = guest_client.post(reverse("households:leave"))

    assert response.status_code == 302
    olya.refresh_from_db()
    assert olya.left_at is not None


def test_owner_cannot_leave(client, yura):
    client.force_login(yura.user)

    response = client.post(reverse("households:leave"))

    assert response.status_code == 403


def test_former_member_rejoins_with_same_color(home, yura, olya):
    slot = olya.color_slot
    remove_member(olya)

    membership = accept_invitation(create_invitation(home, yura.user), olya.user)

    assert membership.pk == olya.pk
    assert membership.left_at is None
    assert membership.color_slot == slot


def test_user_switches_between_families(client, home, olya):
    own = create_household(olya.user, "Мій дім")
    client.force_login(olya.user)
    client.post(reverse("households:switch", args=[own.pk]))
    assert client.get(reverse("households:members")).context["request"].household == own

    response = client.post(reverse("households:switch", args=[home.pk]))

    assert response.status_code == 302
    assert client.get(reverse("households:members")).context["request"].household == home


def test_cannot_switch_to_foreign_family(client, olya, user_household):
    client.force_login(olya.user)

    response = client.post(reverse("households:switch", args=[user_household.pk]))

    assert response.status_code == 404