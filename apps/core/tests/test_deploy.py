import pytest
from django.core.management import call_command
from django.urls import reverse


def test_health_is_public(client, db):
    response = client.get(reverse("core:health"))

    assert response.status_code == 200
    assert response.content == b"ok"


@pytest.mark.django_db
def test_daily_command_runs_without_network(capsys):
    call_command("daily")

    output = capsys.readouterr().out
    assert "Recurring: created 0" in output
    assert "NBU unavailable" in output


def test_daily_url_needs_right_secret(client, db, settings):
    settings.CRON_SECRET = "long-secret"

    assert client.get(reverse("core:daily_task", args=["wrong"])).status_code == 404
    response = client.get(reverse("core:daily_task", args=["long-secret"]))
    assert response.status_code == 200
    assert b"Recurring: created 0" in response.content


def test_daily_url_off_without_secret(client, db, settings):
    settings.CRON_SECRET = ""

    assert client.get(reverse("core:daily_task", args=["anything"])).status_code == 404
