from decimal import Decimal

from apps.core.templatetags.money import money


def test_hryvnia_is_rounded_with_spaces():
    assert money(Decimal("22189.50")) == "22\u202f190\u00a0₴"


def test_foreign_currency_keeps_cents():
    assert money(Decimal("8.99"), "USD") == "$8.99"


def test_negative_and_empty():
    assert money(Decimal("-486")) == "−486\u00a0₴"
    assert money(None) == ""