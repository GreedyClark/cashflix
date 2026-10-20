from django.shortcuts import redirect, render

from .forms import HouseholdForm
from .middleware import SESSION_KEY
from .services import create_household


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