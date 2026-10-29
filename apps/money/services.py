import datetime

from django.db import transaction

from .models import Category, Transaction

DEFAULT_EXPENSE_CATEGORIES = [
    ("Продукти", "shopping-cart", 1),
    ("Кафе", "coffee", 2),
    ("Транспорт", "car", 3),
    ("Комуналка", "home-bolt", 4),
    ("Підписки", "repeat", 5),
    ("Розваги", "device-gamepad-2", 6),
    ("Одяг", "shirt", 7),
    ("Здоров'я", "heart", 1),
    ("Інше", "dots", Category.OTHER_COLOR),
]

DEFAULT_INCOME_CATEGORIES = [
    ("Зарплата", "cash", 3),
    ("Подарунки", "gift", 5),
    ("Інвестиційний дохід", "chart-line", 7),
    ("Інше", "dots", Category.OTHER_COLOR),
]


def create_default_categories(household):
    rows = []
    for kind, items in (
        (Category.Kind.EXPENSE, DEFAULT_EXPENSE_CATEGORIES),
        (Category.Kind.INCOME, DEFAULT_INCOME_CATEGORIES),
    ):
        for order, (name, icon, color) in enumerate(items):
            rows.append(
                Category(household=household, kind=kind, name=name, icon=icon, color_slot=color, order=order)
            )
    return Category.objects.bulk_create(rows)

SNAPSHOT_FIELDS = [
    "type", "date", "title", "note", "account_id", "amount", "currency", "rate", "amount_base",
    "to_account_id", "to_amount", "category_id", "member_id", "source", "created_by_id", "created_at",
]


def snapshot(transaction):
    data = {name: getattr(transaction, name) for name in SNAPSHOT_FIELDS}
    data = {name: str(value) if value is not None else None for name, value in data.items()}
    data["pk"] = transaction.pk
    data["household_id"] = transaction.household_id
    return data


def restore(household, data):
    from .models import Transaction

    pk = data["pk"]
    if data["household_id"] != household.pk or household.transactions.filter(pk=pk).exists():
        return None
    transaction = Transaction(pk=pk, household=household)
    for field in Transaction._meta.concrete_fields:
        if field.attname in data:
            value = data[field.attname]
            setattr(transaction, field.attname, None if value is None else field.to_python(value))
    created_at = transaction.created_at
    transaction.save()
    Transaction.objects.filter(pk=pk).update(created_at=created_at)
    transaction.created_at = created_at
    return transaction


@transaction.atomic
def merge_categories(source, target):
    moved = source.transactions.update(category=target)
    source.recurring_payments.update(category=target)
    for limit in source.limits.all():
        if target.limits.filter(member=limit.member).exists():
            limit.delete()
        else:
            limit.category = target
            limit.save(update_fields=["category"])
    source.delete()
    return moved


TRANSFER_WORDS = ("переказ", "з картки", "на картку", "від:", "поповнення", "transfer")
PAIR_WINDOW = datetime.timedelta(days=2)


def looks_like_transfer(operation):
    title = (operation.title or "").lower()
    return any(word in title for word in TRANSFER_WORDS)


def absorb_halves(transfer):
    window = (transfer.date - PAIR_WINDOW, transfer.date + PAIR_WINDOW)
    candidates = Transaction.objects.filter(household=transfer.household, date__range=window).exclude(pk=transfer.pk)
    halves = list(
        candidates.filter(type=Transaction.Type.EXPENSE, account=transfer.account, amount=transfer.amount)
    ) + list(
        candidates.filter(type=Transaction.Type.INCOME, account=transfer.to_account, amount=transfer.to_amount)
    )
    removed = 0
    for half in halves:
        if half.needs_review or looks_like_transfer(half):
            half.delete()
            removed += 1
    return removed
