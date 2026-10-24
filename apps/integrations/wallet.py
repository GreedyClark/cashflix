import re
from datetime import timedelta

from django.db.models import ProtectedError
from django.utils import timezone

from apps.money.forms import default_account
from apps.money.models import Account, Transaction

from .models import MonobankConnection, WalletCard

TWIN_WINDOW = timedelta(minutes=15)
ALIASES = {
    "monobank": "монобанк",
    "mono": "моно",
    "privatbank": "приватбанк",
    "privat": "приват",
    "oschadbank": "ощадбанк",
    "oschad": "ощад",
    "pumb": "пумб",
    "sense": "сенс",
    "raiffeisen": "райффайзен",
    "ukrsibbank": "укрсиббанк",
    "izibank": "ізібанк",
}
MONOBANK_WORDS = ("моно", "monobank")
SYMBOLS = {"$": "USD", "€": "EUR"}
CREATED = "created"
SKIPPED = "skipped"


def card_key(name):
    words = re.sub(r"[^\w]+", " ", (name or "").casefold()).split()
    return " ".join(ALIASES.get(word, word) for word in words)[:80]


def currency_of(raw_amount, household):
    text = str(raw_amount or "")
    for symbol, code in SYMBOLS.items():
        if symbol in text or code in text.upper():
            return code
    return household.base_currency


def usable_accounts(household):
    return household.accounts.filter(is_archived=False).exclude(kind=Account.Kind.INVESTMENT)


def by_name(accounts, key):
    for account in accounts:
        name = card_key(account.name)
        if name and (name in key or key in name):
            return account
    return None


def looks_like_monobank(key):
    return any(word in key for word in MONOBANK_WORDS)


def monobank_twin(household, amount, moment):
    return household.transactions.filter(
        source=Transaction.Source.MONOBANK,
        amount=amount,
        occurred_at__range=(moment - TWIN_WINDOW, moment + TWIN_WINDOW),
    ).exists()


def free_name(household, title):
    taken = set(household.accounts.values_list("name", flat=True))
    name, number = title, 2
    while name in taken:
        name = f"{title} {number}"
        number += 1
    return name


def fallback(household, membership, token):
    if token.account and not token.account.is_archived:
        return token.account
    unlinked = usable_accounts(household).filter(monobank__isnull=True)
    guess = default_account(household, membership)
    if guess and guess in unlinked:
        return guess
    return unlinked.filter(kind=Account.Kind.CARD).first()


def remember(household, key, title, **fields):
    card, _created = WalletCard.objects.update_or_create(
        household=household, key=key, defaults={"title": title, "last_used_at": timezone.now(), **fields}
    )
    return card


def resolve(household, membership, token, card, currency, amount, moment):
    title = " ".join(str(card or "").split())[:80]
    key = card_key(title)
    if not key:
        return fallback(household, membership, token), None

    saved = WalletCard.objects.filter(household=household, key=key).select_related("account").first()
    if saved:
        saved.last_used_at = timezone.now()
        saved.save(update_fields=["last_used_at"])
        if saved.ignored:
            return None, SKIPPED
        if saved.account and not saved.account.is_archived:
            return saved.account, None

    account = by_name(usable_accounts(household), key)
    if account:
        remember(household, key, title, account=account, ignored=False)
        return account, None

    has_monobank = MonobankConnection.objects.filter(membership__household=household).exists()
    if has_monobank and looks_like_monobank(key):
        remember(household, key, title, account=None, ignored=True)
        return None, SKIPPED
    if monobank_twin(household, amount, moment):
        return None, SKIPPED

    account = Account.objects.create(
        household=household,
        name=free_name(household, title),
        kind=Account.Kind.CARD,
        currency=currency,
        owner=membership,
    )
    remember(household, key, title, account=account, ignored=False, auto_created=True)
    return account, CREATED


def relink(card, account, ignored):
    old = card.account
    card.account = None if ignored else account
    card.ignored = ignored
    card.save(update_fields=["account", "ignored"])
    if not old or old == card.account:
        return
    if card.account and old.currency == card.account.currency:
        old.transactions.filter(source=Transaction.Source.SHORTCUT).update(account=card.account)
    if card.auto_created and not old.transactions.exists() and not old.incoming_transfers.exists() and not old.wallet_cards.exists():
        try:
            old.delete()
        except ProtectedError:
            pass
