import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.core.demo import USERS
from apps.users.models import User


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_demo_button_logs_in_as_yura(client):
    call_command("seed_demo", months=1)

    assert "Увійти в демо" in client.get(reverse("account_login")).content.decode()

    response = client.post(reverse("core:demo_login"))

    assert response.url == reverse("core:home")
    assert client.get(reverse("core:home")).context["user"].email == USERS[0][0]


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_demo_button_without_seed_shows_hint(client):
    response = client.post(reverse("core:demo_login"), follow=True)

    assert "seed_demo" in response.content.decode()


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_demo_login_is_off_in_production(client):
    assert client.post(reverse("core:demo_login")).status_code == 404
    assert "Увійти в демо" not in client.get(reverse("account_login")).content.decode()


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_reset_keeps_session(client):
    call_command("seed_demo", months=1)
    client.post(reverse("core:demo_login"))
    user_id = User.objects.get(email=USERS[0][0]).pk

    call_command("seed_demo", months=1, reset=True)

    response = client.get(reverse("core:home"))
    assert response.status_code == 200
    assert response.context["user"].pk == user_id
    assert response.context["request"].household.name == "Дім (демо)"
