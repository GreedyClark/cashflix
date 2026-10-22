import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.money.categorize import categorize, merchant_key
from apps.money.ingest import CREATED, DUPLICATE, MERGED, ingest
from apps.money.models import Category, MerchantRule, Transaction

MOMENT = timezone.make_aware(datetime.datetime(2026, 10, 20, 14, 30))


@pytest.mark.parametrize("title, key", [
    ("SILPO 1234 KYIV", "silpo"),
    ("Сільпо, ТОВ", "сільпо"),
    ("  Aroma Kava  Lviv ", "aroma kava"),
    ("", ""),
])
def test_merchant_key(title, key):
    assert merchant_key(title) == key


def test_starter_dictionary(home):
    assert categorize(home, "SILPO 1234").category.name == "Продукти"
    assert categorize(home, "Uklon trip").category.name == "Транспорт"
    assert categorize(home, "Bolt Food").category.name == "Кафе"
    assert categorize(home, "Газета Вечірній Київ").category.name == "Інше"


def test_unknown_goes_to_other_with_review(home):
    guess = categorize(home, "Зоомагазин Мурчик")

    assert guess.category.name == "Інше"
    assert guess.needs_review


def test_family_memory_beats_dictionary(home, cafe_or_food):
    MerchantRule.objects.create(household=home, key="silpo", category=cafe_or_food)

    assert categorize(home, "SILPO 77").category == cafe_or_food


@pytest.fixture
def cafe_or_food(home):
    return home.categories.get(kind=Category.Kind.EXPENSE, name="Кафе")


def test_editing_category_teaches_memory(client, yura, home, mono):
    client.force_login(yura.user)
    tx, _ = ingest(home, account=mono, amount=Decimal("300"), title="Зоомагазин Мурчик", source="shortcut", occurred_at=MOMENT)
    pets = Category.objects.create(household=home, name="Тварини", color_slot=2)
    assert tx.needs_review

    client.post(reverse("money:transaction_edit", args=[tx.pk]), {
        "type": "expense", "amount": "300", "title": tx.title, "category": pets.pk, "account": mono.pk,
        "when": "other", "date": "2026-10-20", "member": "",
    })

    tx.refresh_from_db()
    assert (tx.category, tx.needs_review) == (pets, False)
    assert categorize(home, "ЗООМАГАЗИН МУРЧИК").category == pets


def test_same_external_id_is_duplicate(home, mono):
    first, status = ingest(home, account=mono, amount=Decimal("50"), title="АТБ", source="shortcut", occurred_at=MOMENT, external_id="a1")
    again, status_again = ingest(home, account=mono, amount=Decimal("50"), title="АТБ", source="shortcut", occurred_at=MOMENT, external_id="a1")

    assert (status, status_again) == (CREATED, DUPLICATE)
    assert first == again
    assert home.transactions.count() == 1


def test_twin_from_other_source_is_merged(home, mono, yura):
    manual = Transaction.objects.create(
        household=home, account=mono, amount=Decimal("486"), title="Сільпо", category=home.categories.get(name="Продукти", kind="expense"),
        date=MOMENT.date(), occurred_at=MOMENT, member=yura,
    )

    tx, status = ingest(home, account=mono, amount=Decimal("486"), title="SILPO", source="shortcut",
                        occurred_at=MOMENT + datetime.timedelta(minutes=10))

    assert status == MERGED
    assert tx == manual
    assert home.transactions.count() == 1


def test_twin_outside_window_is_new(home, mono):
    ingest(home, account=mono, amount=Decimal("486"), title="Сільпо", source="manual", occurred_at=MOMENT)

    _, status = ingest(home, account=mono, amount=Decimal("486"), title="Сільпо", source="shortcut",
                       occurred_at=MOMENT + datetime.timedelta(minutes=40))

    assert status == CREATED


def test_same_source_twin_is_flagged(home, mono):
    first, _ = ingest(home, account=mono, amount=Decimal("99"), title="Кава", source="shortcut", occurred_at=MOMENT)
    second, status = ingest(home, account=mono, amount=Decimal("99"), title="Кава", source="shortcut",
                            occurred_at=MOMENT + datetime.timedelta(minutes=2))

    assert status == CREATED
    assert second.duplicate_of == first


def test_not_duplicate_and_review_filter(client, yura, home, mono):
    client.force_login(yura.user)
    first, _ = ingest(home, account=mono, amount=Decimal("99"), title="Кава", source="shortcut", occurred_at=MOMENT)
    second, _ = ingest(home, account=mono, amount=Decimal("99"), title="Кава", source="shortcut", occurred_at=MOMENT)

    response = client.get(reverse("money:transactions"), {"review": "on", "month": "2020-01"})
    assert second in [tx for day in response.context["days"] for tx in day["items"]]

    client.post(reverse("money:transaction_not_duplicate", args=[second.pk]))
    second.refresh_from_db()
    assert second.duplicate_of is None
