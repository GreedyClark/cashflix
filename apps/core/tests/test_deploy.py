import pytest
from django.core.management import call_command
from django.urls import reverse


def test_health_is_public(client, db):
    response = client.get(reverse("core:health"))

    assert response.status_code == 200
    assert response.content == b"ok"


@pytest.mark.django_db
def test_daily_runs_without_network(capsys):
    call_command("daily")

    output = capsys.readouterr()
    assert "Recurring: created 0" in output.out
    assert "NBU unavailable" in output.err
