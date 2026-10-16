from django.db import transaction

from .models import Household, Membership


def next_color_slot(household):
    used = set(household.memberships.values_list("color_slot", flat=True))
    for slot in range(1, Membership.MAX_COLOR_SLOTS + 1):
        if slot not in used:
            return slot
    return len(used) % Membership.MAX_COLOR_SLOTS + 1


def add_member(household, user, role=Membership.Role.MEMBER):
    membership, _ = Membership.objects.get_or_create(
        household=household,
        user=user,
        defaults={"role": role, "color_slot": next_color_slot(household)},
    )
    return membership


@transaction.atomic
def create_household(owner, name, base_currency="UAH"):
    from apps.money.services import create_default_categories

    household = Household.objects.create(name=name, base_currency=base_currency)
    add_member(household, owner, role=Membership.Role.OWNER)
    create_default_categories(household)
    return household