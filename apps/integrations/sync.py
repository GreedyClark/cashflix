from collections import Counter
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from apps.money.categorize import MCC, merchant_key
from apps.money.ingest import CREATED, DUPLICATE, ingest
from apps.money.models import Account, Transaction

from . import monobank
from .models import MonobankAccount, MonobankConnection

FIRST_SYNC_DAYS = 7
TRANSFER_WINDOW = timedelta(minutes=2)
TRANSFER = "transfer"
CARD_NAMES = {
    "black": "Чорна",
    "white": "Біла",
    "platinum": "Platinum",
    "iron": "Iron",
    "fop": "ФОП",
    "yellow": "Дитяча",
    "eAid": "єПідтримка",
    "madeInUkraine": "Зроблено в Україні",
}


def card_title(item):
    pans = item.get("maskedPan") or []
    tail = f" ·· {pans[0][-4:]}" if pans else ""
    currency = monobank.CURRENCIES.get(item.get("currencyCode"), "")
    return f"{CARD_NAMES.get(item.get('type'), 'Картка')}{tail} {currency}".strip()


def minor(value):
    return None if value is None else (Decimal(value) / 100).quantize(Decimal("0.01"))


def reconcile(mono_account, bank_balance):
    if bank_balance is None or mono_account.account_id is None:
        return
    account = Account.objects.with_balance().get(pk=mono_account.account_id)
    difference = bank_balance - account.balance
    if difference:
        Account.objects.filter(pk=account.pk).update(opening_balance=account.opening_balance + difference)


def refresh_accounts(connection, info):
    rows = [(item, False, card_title(item)) for item in info.get("accounts", [])]
    rows += [(item, True, f"Банка «{item.get('title', '')}»") for item in info.get("jars", [])]
    for item, is_jar, title in rows:
        code = item.get("currencyCode")
        if code not in monobank.CURRENCIES:
            continue
        limit = minor(item.get("creditLimit")) or Decimal("0")
        balance = minor(item.get("balance"))
        mono_account, _created = MonobankAccount.objects.update_or_create(
            connection=connection,
            mono_id=item["id"],
            defaults={
                "is_jar": is_jar,
                "title": title,
                "currency": monobank.CURRENCIES[code],
                "credit_limit": limit,
                "balance": None if balance is None else balance - limit,
            },
        )
        reconcile(mono_account, mono_account.balance)


def connect(membership, token):
    info = monobank.client_info(token)
    connection = MonobankConnection.objects.filter(membership=membership).first() or MonobankConnection(membership=membership)
    connection.token = token
    connection.client_name = info.get("name", "")
    connection.last_request_at = timezone.now()
    connection.save()
    refresh_accounts(connection, info)
    return connection


def item_moment(item):
    return datetime.fromtimestamp(item["time"], tz=dt_timezone.utc)


def already_transferred(household, account, amount, kind, moment):
    window = (moment - TRANSFER_WINDOW, moment + TRANSFER_WINDOW)
    side = {"to_account": account} if kind == Transaction.Type.INCOME else {"account": account}
    return household.transactions.filter(
        type=Transaction.Type.TRANSFER, amount=amount, occurred_at__range=window, **side
    ).exists()


def transfer_partner(household, account, amount, kind, moment):
    opposite = Transaction.Type.EXPENSE if kind == Transaction.Type.INCOME else Transaction.Type.INCOME
    window = (moment - TRANSFER_WINDOW, moment + TRANSFER_WINDOW)
    return (
        household.transactions.filter(
            source=Transaction.Source.MONOBANK,
            type=opposite,
            amount=amount,
            occurred_at__range=window,
            account__monobank__isnull=False,
            account__currency=account.currency,
        )
        .exclude(account=account)
        .first()
    )


def make_transfer(partner, account):
    if partner.type == Transaction.Type.EXPENSE:
        partner.to_account = account
    else:
        partner.to_account = partner.account
        partner.account = account
    partner.type = Transaction.Type.TRANSFER
    partner.category = None
    partner.to_amount = None
    partner.needs_review = False
    partner.save()
    return partner


CASH_MCC = {6010, 6011}
TRANSFER_MCC = {4829, 6012, 6538, 6540}
CASHBACK_WORDS = ("кешбек", "cashback", "кешбэк")
REFUND_LOOKBACK = timedelta(days=120)


def cash_account(household, membership, currency):
    cash = household.accounts.filter(kind=Account.Kind.CASH, currency=currency, is_archived=False)
    found = cash.filter(owner=membership).first() or cash.filter(owner__isnull=True).first() or cash.first()
    if found:
        return found
    name = "Готівка" if currency == household.base_currency else f"Готівка {currency}"
    return Account.objects.create(household=household, name=name, kind=Account.Kind.CASH, currency=currency, owner=membership)


def bought_there_before(account, title, moment):
    key = merchant_key(title)
    if not key:
        return False
    recent = account.transactions.filter(
        type=Transaction.Type.EXPENSE, amount__gt=0, occurred_at__gte=moment - REFUND_LOOKBACK
    ).values_list("title", flat=True)[:500]
    return any(merchant_key(other) == key for other in recent)


def is_refund(account, item, moment):
    mcc = item.get("mcc")
    title = (item.get("description") or "").lower()
    if mcc in TRANSFER_MCC or mcc in CASH_MCC or any(word in title for word in CASHBACK_WORDS):
        return False
    return mcc in MCC or bought_there_before(account, item.get("description") or "", moment)


def withdraw_cash(mono_account, item, amount, moment):
    account = mono_account.account
    household = account.household
    cash = cash_account(household, mono_account.connection.membership, account.currency)
    Transaction.objects.create(
        household=household,
        type=Transaction.Type.TRANSFER,
        date=timezone.localdate(moment),
        occurred_at=moment,
        title=item.get("description") or "Зняття готівки",
        account=account,
        to_account=cash,
        amount=amount,
        member=mono_account.connection.membership,
        source=Transaction.Source.MONOBANK,
        external_id=item["id"],
    )
    return TRANSFER


def process_item(mono_account, item):
    account = mono_account.account
    household = account.household
    amount = (abs(Decimal(item["amount"])) / 100).quantize(Decimal("0.01"))
    if not amount:
        return DUPLICATE
    kind = Transaction.Type.EXPENSE if item["amount"] < 0 else Transaction.Type.INCOME
    moment = item_moment(item)
    if household.transactions.filter(source=Transaction.Source.MONOBANK, external_id=item["id"]).exists():
        return DUPLICATE
    if already_transferred(household, account, amount, kind, moment):
        return DUPLICATE
    if kind == Transaction.Type.EXPENSE and item.get("mcc") in CASH_MCC:
        return withdraw_cash(mono_account, item, amount, moment)
    partner = transfer_partner(household, account, amount, kind, moment)
    if partner:
        make_transfer(partner, account)
        return TRANSFER
    if kind == Transaction.Type.INCOME and is_refund(account, item, moment):
        kind, amount = Transaction.Type.EXPENSE, -amount
    tx, status = ingest(
        household,
        account=account,
        amount=amount,
        title=item.get("description") or "Monobank",
        source=Transaction.Source.MONOBANK,
        occurred_at=moment,
        external_id=item["id"],
        member=mono_account.connection.membership,
        kind=kind,
        mcc=item.get("mcc"),
        note=item.get("comment", ""),
    )
    if status == CREATED and item.get("mcc") in TRANSFER_MCC and not tx.needs_review:
        tx.needs_review = True
        tx.save(update_fields=["needs_review"])
    return status


def sync_account(mono_account, now=None):
    now = now or timezone.now()
    connection = mono_account.connection
    wait = connection.seconds_to_wait(monobank.STATEMENT_PAUSE, now)
    if wait:
        raise monobank.MonobankRateLimit(wait)
    oldest = now - timedelta(seconds=monobank.MAX_PERIOD - 3600)
    since = max(mono_account.synced_until or now - timedelta(days=FIRST_SYNC_DAYS), oldest)

    connection.last_request_at = now
    connection.save(update_fields=["last_request_at"])
    items = monobank.statement(connection.token, mono_account.mono_id, since.timestamp(), now.timestamp())

    results = Counter()
    ordered = sorted(items, key=lambda row: row["time"])
    with db_transaction.atomic():
        for item in ordered:
            results[process_item(mono_account, item)] += 1
        mono_account.synced_until = now
        if ordered and ordered[-1].get("balance") is not None:
            mono_account.balance = mono_account.own_money(minor(ordered[-1]["balance"]))
        mono_account.save(update_fields=["synced_until", "balance"])
        reconcile(mono_account, mono_account.balance)
    return results
