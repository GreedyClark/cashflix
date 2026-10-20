import pytest
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.users.adapters import SocialAccountAdapter

User = get_user_model()


@pytest.mark.django_db
def test_anonymous_user_is_sent_to_login(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))


@pytest.mark.django_db
def test_login_page_offers_only_google(client):
    response = client.get(reverse("account_login"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Продовжити з Google" in html
    assert 'type="password"' not in html


@pytest.mark.django_db
def test_google_button_redirects_to_google(client, settings):
    settings.SOCIALACCOUNT_PROVIDERS["google"]["APPS"][0]["client_id"] = "test-client-id"

    response = client.post(reverse("google_login"))

    assert response.status_code == 302
    assert response.url.startswith("https://accounts.google.com/")
    assert "test-client-id" in response.url


@pytest.mark.django_db
def test_password_signup_is_disabled(client):
    response = client.post(
        "/accounts/signup/",
        {"email": "new@example.com", "password1": "Strong-pass-123", "password2": "Strong-pass-123"},
    )

    assert response.status_code == 404
    assert not User.objects.filter(email="new@example.com").exists()


def test_adapter_takes_first_name_from_google(rf):
    sociallogin = SocialLogin(user=User(), account=SocialAccount(provider="google"))

    user = SocialAccountAdapter().populate_user(
        rf.get("/"), sociallogin, {"email": "olya@gmail.com", "first_name": "Оля", "last_name": "К."}
    )

    assert user.email == "olya@gmail.com"
    assert user.display_name == "Оля"


def test_logout(auth_client):
    response = auth_client.post(reverse("account_logout"))

    assert response.status_code == 302
    assert auth_client.get(reverse("core:home")).status_code == 302


def test_home_shows_user_name(auth_client, user):
    response = auth_client.get(reverse("core:home"))

    assert user.name in response.content.decode()