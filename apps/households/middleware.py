from django.db.models import prefetch_related_objects
from django.shortcuts import redirect
from django.urls import reverse

from .models import Membership

SESSION_KEY = "household_id"
EXEMPT_PREFIXES = ("/accounts/", "/admin/", "/static/", "/onboarding/", "/join/")


class CurrentHouseholdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.household = None
        request.membership = None

        if request.user.is_authenticated:
            membership = self.find_membership(request)
            if membership:
                prefetch_related_objects([membership.household], "memberships__user")
                request.membership = membership
                request.household = membership.household
                request.session[SESSION_KEY] = membership.household_id
            elif not request.path.startswith(EXEMPT_PREFIXES):
                return redirect(reverse("households:onboarding"))

        return self.get_response(request)

    @staticmethod
    def find_membership(request):
        memberships = Membership.objects.filter(user=request.user).select_related("household")
        household_id = request.session.get(SESSION_KEY)
        if household_id:
            membership = memberships.filter(household_id=household_id).first()
            if membership:
                return membership
        return memberships.first()