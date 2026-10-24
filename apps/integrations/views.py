import secrets

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
from .models import MonobankAccount, MonobankConnection, ShortcutToken, WalletCard
from .sync import connect, reconcile, refresh_accounts, sync_account
from .wallet import relink

SKIP = ""
NEW = "new"


def create_account_for(item, membership):
    kind = Account.Kind.SAVINGS if item.is_jar else Account.Kind.CARD
    name = item.suggested_name
    existing = set(membership.household.accounts.values_list("name", flat=True))
    number = 2
    while name in existing:
        name = f"{item.suggested_name} {number}"
        number += 1
    return Account.objects.create(
        household=membership.household, name=name, kind=kind, currency=item.currency, owner=membership
    )


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

    accounts = list(usable_accounts(request.household))
    wallet_cards = list(WalletCard.objects.filter(household=request.household).select_related("account"))
    for card in wallet_cards:
        currency = card.account.currency if card.account else None
        card.choices = [a for a in accounts if currency is None or a.currency == currency]

    context = {
        "wallet_cards": wallet_cards,
        "token": token,
        "form": form,
        "raw_token": request.session.pop("new_shortcut_token", None),
        "endpoint": request.build_absolute_uri(reverse("integrations:shortcut_api")),
        "connection": connection,
        "mono_accounts": mono_accounts,
        "shortcut_accounts": usable_accounts(request.household),
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
        value = request.POST.get(f"link_{item.pk}", SKIP)
        if value == NEW:
            chosen[item.pk] = NEW
            continue
        account = accounts.get(value)
        if account and account.currency == item.currency:
            chosen[item.pk] = account
    picked = [account.pk for account in chosen.values() if account != NEW]
    if len(set(picked)) != len(picked):
        messages.error(request, _("Один рахунок CashFlix можна прив'язати лише до однієї картки Monobank."))
        return redirect("integrations:connections")
    try:
        with transaction.atomic():
            connection.accounts.update(account=None)
            for item in connection.accounts.all():
                if item.pk in chosen:
                    account = chosen[item.pk]
                    item.account = create_account_for(item, request.membership) if account == NEW else account
                    item.save(update_fields=["account"])
                    reconcile(item, item.balance)
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
def monobank_webhook_toggle(request):
    connection = get_object_or_404(MonobankConnection, membership=request.membership)
    if not request.is_secure():
        messages.error(request, _("Миттєві операції працюють лише на сайті з HTTPS, тобто після деплою."))
        return redirect("integrations:connections")
    enable = not connection.webhook_secret
    secret = secrets.token_urlsafe(24) if enable else ""
    url = request.build_absolute_uri(reverse("integrations:monobank_webhook", args=[secret])) if enable else ""
    connection.webhook_secret = secret
    connection.save(update_fields=["webhook_secret"])
    try:
        monobank.set_webhook(connection.token, url)
    except monobank.MonobankError as error:
        connection.webhook_secret = ""
        connection.save(update_fields=["webhook_secret"])
        bank_error(request, error)
    else:
        if enable:
            messages.success(request, _("Готово: нові операції Monobank приходитимуть одразу після оплати."))
        else:
            messages.success(request, _("Миттєві операції вимкнено. Оновлюйте картки кнопкою «Оновити»."))
    return redirect("integrations:connections")


@require_POST
def monobank_disconnect(request):
    connection = MonobankConnection.objects.filter(membership=request.membership).first()
    if connection and connection.webhook_secret:
        try:
            monobank.set_webhook(connection.token, "")
        except monobank.MonobankError:
            pass
    MonobankConnection.objects.filter(membership=request.membership).delete()
    messages.success(request, _("Monobank відключено. Вже підтягнуті операції лишилися."))
    return redirect("integrations:connections")


@require_POST
def wallet_links(request):
    accounts = {str(a.pk): a for a in usable_accounts(request.household)}
    for card in WalletCard.objects.filter(household=request.household).select_related("account"):
        value = request.POST.get(f"card_{card.pk}")
        if value is None:
            continue
        if value == SKIP:
            relink(card, None, ignored=True)
        elif value in accounts:
            relink(card, accounts[value], ignored=False)
    messages.success(request, _("Картки з Гаманця збережено."))
    return redirect("integrations:connections")
