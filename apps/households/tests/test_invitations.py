from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.households.models import Invitation
from apps.households.services import accept_invitation, add_member, create_invitation


@pytest.fixture
def invitation(home):
    owner = home.memberships.get().user
    return create_invitation(home, owner)


@pytest.fixture
def guest(django_user_model):
    return django_user_model.objects.create_user(email="olya@gmail.com", password="x", display_name="Оля")


def test_invitation_is_active_for_a_week(invitation):
    assert invitation.is_active
    assert invitation.days_left == 6
    assert len(invitation.token) >= 20


def test_new_invitation_revokes_previous(home, invitation):
    newer = create_invitation(home, invitation.created_by)

    invitation.refresh_from_db()
    assert invitation.is_revoked
    assert list(home.invitations.active()) == [newer]


def test_accept_adds_member_once(invitation, guest):
    membership = accept_invitation(invitation, guest)

    assert membership.household == invitation.household
    assert membership.color_slot == 2
    assert accept_invitation(invitation, guest) is None


def test_expired_invitation_is_not_active(invitation):
    invitation.expires_at = timezone.now() - timedelta(minutes=1)
    invitation.save()

    assert not invitation.is_active


def test_anonymous_sees_invite_with_google_button(client, invitation):
    response = client.get(invitation.get_absolute_url())
    html = response.content.decode()

    assert response.status_code == 200
    assert invitation.household.name in html
    assert "Продовжити з Google" in html
    assert f'name="next" value="{invitation.get_absolute_url()}"' in html


@pytest.mark.django_db
def test_unknown_token_shows_invalid_page(client):
    response = client.get(reverse("households:join", args=["nope"]))

    assert response.status_code == 404
    assert "Запрошення недійсне" in response.content.decode()


def test_logged_in_guest_confirms_and_joins(client, invitation, guest):
    client.force_login(guest)

    page = client.get(invitation.get_absolute_url())
    assert page.status_code == 200
    assert not invitation.household.memberships.filter(user=guest).exists()

    response = client.post(invitation.get_absolute_url())

    assert response.status_code == 302
    assert invitation.household.memberships.filter(user=guest).exists()
    assert client.get(reverse("core:home")).wsgi_request.household == invitation.household
    invitation.refresh_from_db()
    assert invitation.accepted_by == guest


def test_used_invitation_cannot_be_reused(client, invitation, guest, django_user_model):
    accept_invitation(invitation, guest)
    stranger = django_user_model.objects.create_user(email="x@gmail.com", password="x")
    client.force_login(stranger)

    response = client.post(invitation.get_absolute_url())

    assert response.status_code == 404
    assert not invitation.household.memberships.filter(user=stranger).exists()


def test_existing_member_is_sent_home(client, invitation):
    client.force_login(invitation.created_by)

    response = client.get(invitation.get_absolute_url())

    assert response.status_code == 302
    assert response.url == reverse("core:home")


def test_members_page_lists_members(auth_client, user):
    response = auth_client.get(reverse("households:members"))

    assert response.status_code == 200
    assert user.email in response.content.decode()


def test_owner_creates_and_revokes_link(auth_client, user_household):
    auth_client.post(reverse("households:invitation_create"))
    assert user_household.invitations.active().count() == 1

    page = auth_client.get(reverse("households:members")).content.decode()
    assert user_household.invitations.active().get().token in page

    auth_client.post(reverse("households:invitation_revoke"))
    assert user_household.invitations.active().count() == 0


def test_member_cannot_create_link(client, user_household, guest):
    add_member(user_household, guest)
    client.force_login(guest)

    response = client.post(reverse("households:invitation_create"))

    assert response.status_code == 403
    assert not Invitation.objects.exists()