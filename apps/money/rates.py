from decimal import Decimal

from django.utils.translation import gettext as _


class RateNotFound(Exception):
    pass


def uah_rate(currency, on_date):
    from .models import ExchangeRate

    if currency == "UAH":
        return Decimal("1")

    rate = (
        ExchangeRate.objects.filter(currency=currency, date__lte=on_date)
        .order_by("-date")
        .values_list("rate", flat=True)
        .first()
    )
    if rate is None:
        raise RateNotFound(_("Немає курсу %(currency)s на %(date)s") % {"currency": currency, "date": on_date})
    return rate


def convert_rate(currency, base_currency, on_date):
    if currency == base_currency:
        return Decimal("1")
    return uah_rate(currency, on_date) / uah_rate(base_currency, on_date)