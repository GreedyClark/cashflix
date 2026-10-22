from datetime import timedelta

from django.db import IntegrityError, transaction as db_transaction
from django.db.models import Q
from django.utils import timezone

from .categorize import categorize
from .models import Transaction

TWIN_WINDOW = timedelta(minutes=15)
CREATED, DUPLICATE, MERGED = "created", "duplicate", "merged"


def find_twin(household, account, amount, kind, moment):
    window = (moment - TWIN_WINDOW, moment + TWIN_WINDOW)
    same_time = Q(occurred_at__range=window) | Q(occurred_at__isnull=True, created_at__range=window)
    return (
        household.transactions.filter(account=account, amount=amount, type=kind)
        .filter(same_time)
        .order_by("created_at")
        .first()
    )


def enrich(twin, guess, title):
    changed = []
    if twin.needs_review and guess and not guess.needs_review:
        twin.category = guess.category
        twin.needs_review = False
        changed += ["category", "needs_review"]
    if not twin.title and title:
        twin.title = title
        changed.append("title")
    if changed:
        twin.save(update_fields=changed)
    return twin


def ingest(household, *, account, amount, title, source, occurred_at=None, external_id="", member=None,
           kind=Transaction.Type.EXPENSE, category=None, mcc=None, note=""):
    occurred_at = occurred_at or timezone.now()
    if external_id:
        existing = household.transactions.filter(source=source, external_id=external_id).first()
        if existing:
            return existing, DUPLICATE

    guess = None if category else categorize(household, title, kind, mcc)
    twin = find_twin(household, account, amount, kind, occurred_at)
    if twin and twin.source != source:
        return enrich(twin, guess, title), MERGED

    tx = Transaction(
        household=household,
        type=kind,
        date=timezone.localdate(occurred_at),
        occurred_at=occurred_at,
        title=title[:120],
        note=note,
        account=account,
        amount=amount,
        category=category or guess.category,
        member=member,
        source=source,
        external_id=external_id,
        needs_review=bool(guess and guess.needs_review),
        duplicate_of=twin,
    )
    try:
        with db_transaction.atomic():
            tx.save()
    except IntegrityError:
        return household.transactions.get(source=source, external_id=external_id), DUPLICATE
    return tx, CREATED
