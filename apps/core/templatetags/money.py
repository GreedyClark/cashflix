import datetime
from decimal import ROUND_HALF_UP, Decimal

from django import template
from django.utils import dateformat, timezone
from django.utils.translation import gettext as _

register = template.Library()

SYMBOLS = {"UAH": "₴", "USD": "$", "EUR": "€"}
THIN_SPACE = " "


@register.filter
def money(value, currency="UAH"):
    if value in (None, ""):
        return ""
    amount = Decimal(value)
    sign = "−" if amount < 0 else ""
    amount = abs(amount)

    if currency == "UAH":
        amount = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{sign}{amount:,}".replace(",", THIN_SPACE) + " ₴"

    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{sign}{SYMBOLS.get(currency, currency)}{amount:,}".replace(",", THIN_SPACE)


@register.filter
def day_label(value):
    today = timezone.localdate()
    if value == today:
        return _("Сьогодні")
    if value == today - datetime.timedelta(days=1):
        return _("Вчора")
    return f"{dateformat.format(value, 'j E')}, {dateformat.format(value, 'l').lower()}"


@register.filter
def absolute(value):
    return abs(value) if value is not None else value
