from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import HouseholdForm
from .middleware import SESSION_KEY
from .models import Invitation, Membership
from .services import accept_invitation, create_household, create_invitation, month_spending, remove_member


def onboarding(request):
    if request.household:
        return redirect("core:home")

    form = HouseholdForm(request.POST or None, initial={"name": "Дім"})
    if request.method == "POST" and form.is_valid():
        household = create_household(
            request.user, form.cleaned_data["name"], base_currency=form.cleaned_data["base_currency"]
        )
        request.session[SESSION_KEY] = household.pk
        return redirect("core:home")

    return render(request, "households/onboarding.html", {"form": form})


def members(request):
    household = request.household
    invitation = household.invitations.active().first()
    context = {
        **month_spending(household),
        "invitation": invitation,
        "invite_url": request.build_absolute_uri(invitation.get_absolute_url()) if invitation else "",
        "is_owner": request.membership.is_owner,
        "other_memberships": request.user.memberships.active()
        .exclude(household=household)
        .select_related("household"),
    }
    return render(request, "households/members.html", context)


@require_POST
def switch(request, pk):
    membership = get_object_or_404(Membership.objects.active(), household_id=pk, user=request.user)
    request.session[SESSION_KEY] = membership.household_id
    return redirect("households:members")


def owner_required(request):
    if not request.membership or not request.membership.is_owner:
        raise PermissionDenied


@require_POST
def invitation_create(request):
    owner_required(request)
    create_invitation(request.household, request.user)
    return redirect("households:members")


@require_POST
def invitation_revoke(request):
    owner_required(request)
    request.household.invitations.active().update(is_revoked=True)
    messages.success(request, _("Посилання скасовано. Ним більше не можна скористатися."))
    return redirect("households:members")


@require_POST
def member_remove(request, pk):
    owner_required(request)
    membership = get_object_or_404(
        Membership.objects.active().select_related("user"), pk=pk, household=request.household
    )
    if membership.is_owner:
        raise PermissionDenied
    remove_member(membership)
    text = _("%(name)s більше не в сім'ї. Операції залишились в історії.")
    messages.success(request, text % {"name": membership.user.name})
    return redirect("households:members")


@require_POST
def leave(request):
    if request.membership.is_owner:
        raise PermissionDenied
    name = request.household.name
    remove_member(request.membership)
    request.session.pop(SESSION_KEY, None)
    messages.success(request, _("Ви вийшли із сім'ї «%(name)s».") % {"name": name})
    return redirect("core:home")


@login_not_required
def join(request, token):
    invitation = Invitation.objects.select_related("household", "created_by").filter(token=token).first()
    if invitation is None or not invitation.is_active:
        return render(request, "households/join_invalid.html", status=404)

    context = {"invitation": invitation, "inviter": invitation.created_by, "household": invitation.household}

    if not request.user.is_authenticated:
        context["redirect_field"] = format_html('<input type="hidden" name="next" value="{}">', request.path)
        return render(request, "households/join_login.html", context)

    if invitation.household.memberships.active().filter(user=request.user).exists():
        request.session[SESSION_KEY] = invitation.household_id
        return redirect("core:home")

    if request.method == "POST":
        membership = accept_invitation(invitation, request.user)
        if membership is None:
            return render(request, "households/join_invalid.html", status=404)
        request.session[SESSION_KEY] = membership.household_id
        messages.success(request, _("Ви приєдналися до «%(name)s».") % {"name": membership.household.name})
        return redirect("core:home")

    return render(request, "households/join_confirm.html", context)