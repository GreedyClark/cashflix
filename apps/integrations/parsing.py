import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.dateparse import parse_datetime

AMOUNT_CHARS = re.compile(r"[^\d,.\-]")
MAX_AMOUNT = Decimal("10000000")
MAX_SKEW = timedelta(days=31)


class BadPayload(ValueError):
    pass


def parse_amount(value):
    if isinstance(value, (int, float, Decimal)):
        text = str(value)
    else:
        text = AMOUNT_CHARS.sub("", str(value or ""))
    if "," in text and "." in text:
        decimal_mark = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal_mark == "," else ","
        text = text.replace(thousands, "").replace(decimal_mark, ".")
    else:
        text = text.replace(",", ".")
    try:
        amount = abs(Decimal(text)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise BadPayload("amount")
    if amount <= 0 or amount >= MAX_AMOUNT:
        raise BadPayload("amount")
    return amount


def parse_moment(value):
    if not value:
        return timezone.now()
    try:
        moment = parse_datetime(str(value).strip().replace(" ", "T", 1))
    except ValueError:
        moment = None
    if moment is None:
        for pattern in ("%d.%m.%Y %H:%M", "%d.%m.%Y, %H:%M", "%d.%m.%Y"):
            try:
                moment = datetime.strptime(str(value).strip(), pattern)
                break
            except ValueError:
                continue
    if moment is None:
        return timezone.now()
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    if abs(moment - timezone.now()) > MAX_SKEW:
        return timezone.now()
    return moment
