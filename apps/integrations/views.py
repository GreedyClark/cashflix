from django import forms
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.money.models import Account

from . import monobank
from .models import MonobankAccount, MonobankConnection, ShortcutToken
from .sync import connect, refresh_accounts, sync_account

SKIP = ""


class DefaultAccountForm(forms.ModelForm):
    account = forms.ModelChoiceField(queryset=None, required=False, empty_label=gettext_lazy("Моя картка за замовчуванням"))

    class Meta:
        model = ShortcutToken
        fields = ["account"]

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = usable_accounts(household)


def usable_accounts(household):
    return household.accounts.filter(is_archived=False).exclude(kind=Account.Kind.INVESTMENT)


def connections(request):
    token = ShortcutToken.objects.filter(membership=request.membership).select_related("account").first()
    form = DefaultAccountForm(request.POST or None, instance=token, household=request.household) if token else None
    if request.method == "POST" and form and form.is_valid():
        form.save()
        return redirect("integrations:connections")

    connection = MonobankConnection.objects.filter(membership=request.membership).first()
    mono_accounts = []
    if connection:
        accounts = list(usable_accounts(request.household))
        for item in connection.accounts.select_related("account"):
            item.choices = [a for a in accounts if a.currency == item.currency]
            mono_accounts.append(item)

    context = {
        "token": token,
        "form": form,
        "raw_token": request.session.pop("new_shortcut_token", None),
        "endpoint": request.build_absolute_uri(reverse("integrations:shortcut_api")),
        "connection": connection,
        "mono_accounts": mono_accounts,
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


def bank_error(request, error):
    if isinstance(error, monobank.MonobankAuthError):
        messages.error(request, _("Monobank не прийняв токен. Перевірте, що скопіювали його повністю."))
    elif isinstance(error, monobank.MonobankRateLimit):
        seconds = error.args[0] if error.args and isinstance(error.args[0], int) else 60
        messages.error(request, _("Monobank дозволяє запит раз на хвилину. Спробуйте через %(seconds)s с.") % {"seconds": seconds})
    else:
        messages.error(request, _("Monobank зараз недоступний. Спробуйте пізніше."))


@require_POST
def monobank_connect(request):
    raw = request.POST.get("mono_token", "").strip()
    if not raw:
        messages.error(request, _("Вставте токен Monobank."))
        return redirect("integrations:connections")
    try:
        connection = connect(request.membership, raw)
    except monobank.MonobankError as error:
        bank_error(request, error)
    else:
        message = _("Monobank підключено: %(name)s. Оберіть, які картки куди записувати.")
        messages.success(request, message % {"name": connection.client_name})
    return redirect("integrations:connections")


@require_POST
def monobank_refresh(request):
    connection = get_object_or_404(MonobankConnection, membership=request.membership)
    try:
        refresh_accounts(connection, monobank.client_info(connection.token))
    except monobank.MonobankError as error:
        bank_error(request, error)
    else:
        messages.success(request, _("Список карток оновлено."))
    return redirect("integrations:connections")


@require_POST
def monobank_links(request):
    connection = get_object_or_404(MonobankConnection, membership=request.membership)
    accounts = {str(a.pk): a for a in usable_accounts(request.household)}
    chosen = {}
    for item in connection.accounts.all():
        account = accounts.get(request.POST.get(f"link_{item.pk}", SKIP))
        if account and account.currency == item.currency:
            chosen[item.pk] = account
    if len({a.pk for a in chosen.values()}) != len(chosen):
        messages.error(request, _("Один рахунок CashFlix можна прив'язати лише до однієї картки Monobank."))
        return redirect("integrations:connections")
    try:
        with transaction.atomic():
            connection.accounts.update(account=None)
            for item in connection.accounts.all():
                if item.pk in chosen:
                    item.account = chosen[item.pk]
                    item.save(update_fields=["account"])
    except IntegrityError:
        messages.error(request, _("Цей рахунок уже прив'язаний до Monobank іншого учасника."))
        return redirect("integrations:connections")
    messages.success(request, _("Збережено. Натисніть «Оновити» біля картки, щоб підтягнути операції."))
    return redirect("integrations:connections")


@require_POST
def monobank_sync(request, pk):
    item = get_object_or_404(MonobankAccount, pk=pk, connection__membership=request.membership, account__isnull=False)
    try:
        results = sync_account(item)
    except monobank.MonobankError as error:
        bank_error(request, error)
    else:
        text = _("%(name)s: нових %(created)s, об'єднано з наявними %(merged)s, переказів %(transfers)s, вже були %(duplicates)s.")
        messages.success(request, text % {
            "name": item.account.name,
            "created": results["created"],
            "merged": results["merged"],
            "transfers": results["transfer"],
            "duplicates": results["duplicate"],
        })
    return redirect("integrations:connections")


@require_POST
def monobank_disconnect(request):
    MonobankConnection.objects.filter(membership=request.membership).delete()
    messages.success(request, _("Monobank відключено. Вже підтягнуті операції лишилися."))
    return redirect("integrations:connections")
