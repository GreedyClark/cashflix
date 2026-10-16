import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_anonymous_user_is_sent_to_login(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))


@pytest.mark.django_db
def test_login_page_is_public_and_in_ukrainian(client):
    response = client.get(reverse("account_login"))

    assert response.status_code == 200
    assert "Увійти" in response.content.decode()


@pytest.mark.django_db
def test_signup_creates_user_and_logs_in(client):
    response = client.post(
        reverse("account_signup"),
        {"email": "new@example.com", "password1": "Strong-pass-123", "password2": "Strong-pass-123"},
    )

    assert response.status_code == 302
    assert User.objects.filter(email="new@example.com").exists()
    assert client.get(reverse("core:home")).status_code == 200


def test_login_with_email(client, user):
    response = client.post(reverse("account_login"), {"login": "me@example.com", "password": "pass12345"})

    assert response.status_code == 302
    assert client.get(reverse("core:home")).status_code == 200


def test_wrong_password_shows_error(client, user):
    response = client.post(reverse("account_login"), {"login": "me@example.com", "password": "wrong"})

    assert response.status_code == 200
    assert response.context["form"].errors


def test_logout(auth_client):
    response = auth_client.post(reverse("account_logout"))

    assert response.status_code == 302
    assert auth_client.get(reverse("core:home")).status_code == 302


def test_home_shows_user_name(auth_client, user):
    response = auth_client.get(reverse("core:home"))

    assert user.name in response.content.decode()