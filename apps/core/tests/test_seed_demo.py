import pytest
from django.core.management import call_command

from apps.households.models import Household


@pytest.mark.django_db
def test_seed_demo_creates_household_and_can_be_reset():
    call_command("seed_demo", months=2)
    home = Household.objects.get(name="Дім (демо)")

    assert home.memberships.count() == 2
    assert home.transactions.exists()
    assert home.limits.count() == 5
    assert home.goals.count() == 3

    call_command("seed_demo", months=2, reset=True)

    assert Household.objects.filter(name="Дім (демо)").count() == 1