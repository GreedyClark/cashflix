from django import forms
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.money.models import Account

from .models import ShortcutToken


class DefaultAccountForm(forms.ModelForm):
    account = forms.ModelChoiceField(queryset=None, required=False, empty_label=gettext_lazy("Моя картка за замовчуванням"))

    class Meta:
        model = ShortcutToken
        fields = ["account"]

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = household.accounts.filter(is_archived=False).exclude(
            kind=Account.Kind.INVESTMENT
        )


def connections(request):
    token = ShortcutToken.objects.filter(membership=request.membership).select_related("account").first()
    form = DefaultAccountForm(request.POST or None, instance=token, household=request.household) if token else None
    if request.method == "POST" and form and form.is_valid():
        form.save()
        return redirect("integrations:connections")
    context = {
        "token": token,
        "form": form,
        "raw_token": request.session.pop("new_shortcut_token", None),
        "endpoint": request.build_absolute_uri(reverse("integrations:shortcut_api")),
        "accounts": request.household.accounts.filter(is_archived=False).exclude(kind=Account.Kind.INVESTMENT),
    }
    return render(request, "integrations/connections.html", context)


@require_POST
def token_issue(request):
    _token, raw = ShortcutToken.issue(request.membership)
    request.session["new_shortcut_token"] = raw
    return redirect("integrations:connections")


@require_POST
def token_revoke(request):
    ShortcutToken.objects.filter(membership=request.membership).delete()
    return redirect("integrations:connections")
