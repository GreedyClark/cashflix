from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Household, Invitation, Membership


def next_color_slot(household):
    used = set(household.memberships.values_list("color_slot", flat=True))
    for slot in range(1, Membership.MAX_COLOR_SLOTS + 1):
        if slot not in used:
            return slot
    return len(used) % Membership.MAX_COLOR_SLOTS + 1


def add_member(household, user, role=Membership.Role.MEMBER):
    membership, created = Membership.objects.get_or_create(
        household=household,
        user=user,
        defaults={"role": role, "color_slot": next_color_slot(household)},
    )
    if not created and membership.left_at:
        membership.left_at = None
        membership.save(update_fields=["left_at"])
    return membership


def remove_member(membership):
    if membership.is_owner:
        raise ValueError("Owner cannot leave the household")
    membership.left_at = timezone.now()
    membership.save(update_fields=["left_at"])


@transaction.atomic
def create_household(owner, name, base_currency="UAH"):
    from apps.money.services import create_default_categories

    household = Household.objects.create(name=name, base_currency=base_currency)
    add_member(household, owner, role=Membership.Role.OWNER)
    create_default_categories(household)
    return household


@transaction.atomic
def create_invitation(household, created_by):
    household.invitations.active().update(is_revoked=True)
    return Invitation.objects.create(household=household, created_by=created_by)


@transaction.atomic
def accept_invitation(invitation, user):
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if not invitation.is_active:
        return None
    membership = add_member(invitation.household, user)
    invitation.accepted_by = user
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_by", "accepted_at"])
    return membership


def month_spending(household, today=None):
    from apps.money.models import Transaction

    today = today or timezone.localdate()
    period = household.period(today)
    month_start = period.start
    in_month = Q(transactions__type=Transaction.Type.EXPENSE, transactions__date__gte=month_start)

    memberships = list(
        household.memberships.select_related("user").annotate(
            spent=Coalesce(Sum("transactions__amount_base", filter=in_month), Decimal("0")),
            operations=Count("transactions", filter=in_month),
        )
    )
    shared = household.transactions.expenses().filter(date__gte=month_start, member__isnull=True).total_base()
    total = sum((m.spent for m in memberships), shared)

    segments = [{"name": m.user.name, "amount": m.spent, "color": f"color-{m.color_slot}"} for m in memberships]
    segments.append({"name": _("Спільне"), "amount": shared, "color": "color-shared"})
    segments = [s for s in segments if s["amount"] > 0]
    for segment in segments:
        segment["percent"] = round(segment["amount"] / total * 100) if total else 0

    return {
        "memberships": [m for m in memberships if m.is_active],
        "former_members": [m for m in memberships if not m.is_active],
        "segments": segments,
        "total": total,
        "month": month_start,
        "period": period,
    }
