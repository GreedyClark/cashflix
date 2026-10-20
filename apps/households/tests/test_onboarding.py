from django.urls import reverse

from apps.households.models import Household, Membership
from apps.households.services import add_member


def test_user_without_household_is_sent_to_onboarding(newcomer_client):
    response = newcomer_client.get(reverse("core:home"))

    assert response.status_code == 302
    assert response.url == reverse("households:onboarding")


def test_onboarding_page_shows_user(newcomer_client, user):
    response = newcomer_client.get(reverse("households:onboarding"))

    assert response.status_code == 200
    assert user.email in response.content.decode()


def test_onboarding_creates_household(newcomer_client, user):
    response = newcomer_client.post(reverse("households:onboarding"), {"name": "Дім", "base_currency": "UAH"})

    assert response.status_code == 302
    assert response.url == reverse("core:home")
    household = Household.objects.get(name="Дім")
    assert household.memberships.get().user == user
    assert household.memberships.get().role == Membership.Role.OWNER
    assert household.categories.exists()
    assert newcomer_client.get(reverse("core:home")).status_code == 200


def test_onboarding_requires_name(newcomer_client):
    response = newcomer_client.post(reverse("households:onboarding"), {"name": "  ", "base_currency": "UAH"})

    assert response.status_code == 200
    assert response.context["form"].errors["name"]
    assert not Household.objects.exists()


def test_user_with_household_skips_onboarding(auth_client):
    response = auth_client.get(reverse("households:onboarding"))

    assert response.status_code == 302
    assert response.url == reverse("core:home")


def test_request_household_is_users_own(auth_client, user_household, home):
    request = auth_client.get(reverse("core:home")).wsgi_request

    assert request.household == user_household
    assert request.household != home
    assert request.membership.user == request.user


def test_household_from_session_is_used(auth_client, user, home):
    add_member(home, user)
    session = auth_client.session
    session["household_id"] = home.pk
    session.save()

    request = auth_client.get(reverse("core:home")).wsgi_request

    assert request.household == home


def test_foreign_household_in_session_is_ignored(auth_client, user_household, home):
    session = auth_client.session
    session["household_id"] = home.pk
    session.save()

    request = auth_client.get(reverse("core:home")).wsgi_request

    assert request.household == user_household


def test_sidebar_shows_household_name(auth_client, user_household):
    response = auth_client.get(reverse("core:home"))

    assert user_household.name in response.content.decode()


def test_logout_works_without_household(newcomer_client):
    response = newcomer_client.post(reverse("account_logout"))

    assert response.status_code == 302
    assert response.url == reverse("account_login")