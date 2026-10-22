from collections import Counter
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from apps.money.ingest import DUPLICATE, ingest
from apps.money.models import Transaction

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


def refresh_accounts(connection, info):
    rows = [(item["id"], False, card_title(item), item.get("currencyCode")) for item in info.get("accounts", [])]
    rows += [(item["id"], True, f"Банка «{item.get('title', '')}»", item.get("currencyCode")) for item in info.get("jars", [])]
    for mono_id, is_jar, title, code in rows:
        if code not in monobank.CURRENCIES:
            continue
        MonobankAccount.objects.update_or_create(
            connection=connection,
            mono_id=mono_id,
            defaults={"is_jar": is_jar, "title": title, "currency": monobank.CURRENCIES[code]},
        )


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
    partner = transfer_partner(household, account, amount, kind, moment)
    if partner:
        make_transfer(partner, account)
        return TRANSFER
    _tx, status = ingest(
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
    with db_transaction.atomic():
        for item in sorted(items, key=lambda row: row["time"]):
            results[process_item(mono_account, item)] += 1
        mono_account.synced_until = now
        mono_account.save(update_fields=["synced_until"])
    return results
