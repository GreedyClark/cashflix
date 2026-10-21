from decimal import ROUND_HALF_UP, Decimal

from django import template

register = template.Library()

SYMBOLS = {"UAH": "₴", "USD": "$", "EUR": "€"}
THIN_SPACE = "\u202f"


@register.filter
def money(value, currency="UAH"):
    if value in (None, ""):
        return ""
    amount = Decimal(value)
    sign = "−" if amount < 0 else ""
    amount = abs(amount)

    if currency == "UAH":
        amount = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{sign}{amount:,}".replace(",", THIN_SPACE) + "\u00a0₴"

    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{sign}{SYMBOLS.get(currency, currency)}{amount:,}".replace(",", THIN_SPACE)