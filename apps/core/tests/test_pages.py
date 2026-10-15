import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_home_page_renders(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    assert "CashFlix" in response.content.decode()


@pytest.mark.django_db
def test_home_is_marked_active_in_menu(client):
    response = client.get(reverse("core:home"))
    active = [item for item in response.context["main_menu"] if item["active"]]

    assert [item["icon"] for item in active] == ["home"]


@pytest.mark.django_db
def test_page_is_in_ukrainian(client):
    response = client.get(reverse("core:home"))

    assert '<html lang="uk"' in response.content.decode()