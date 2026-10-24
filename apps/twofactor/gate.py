from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from . import devices
from .models import SecondFactor

SESSION_KEY = "twofactor_user"
OPEN_PREFIXES = ("/static/", "/security/confirm/", "/accounts/logout/", "/api/", "/health/", "/tasks/")


def passed(request):
    return request.session.get(SESSION_KEY) == request.user.pk


def mark_passed(request):
    request.session[SESSION_KEY] = request.user.pk


def required(user):
    factor = SecondFactor.objects.filter(user=user).only("method").first()
    return bool(factor and factor.enabled)


class SecondFactorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and not request.path.startswith(OPEN_PREFIXES)
            and not passed(request)
            and required(request.user)
        ):
            if devices.recognize(request, request.user):
                mark_passed(request)
            else:
                return self.challenge(request)
        return self.get_response(request)

    @staticmethod
    def challenge(request):
        url = reverse("twofactor:confirm")
        if request.method == "GET" and not request.headers.get("HX-Request"):
            request.session["twofactor_next"] = request.get_full_path()
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=204)
            response["HX-Redirect"] = url
            return response
        return redirect(url)
