from django.urls import reverse


def test_home_page_renders(auth_client):
    response = auth_client.get(reverse("core:home"))

    assert response.status_code == 200
    assert "CashFlix" in response.content.decode()


def test_home_is_marked_active_in_menu(auth_client):
    response = auth_client.get(reverse("core:home"))
    active = [item for item in response.context["main_menu"] if item["active"]]

    assert [item["icon"] for item in active] == ["home"]


def test_page_is_in_ukrainian(auth_client):
    response = auth_client.get(reverse("core:home"))

    assert '<html lang="uk"' in response.content.decode()