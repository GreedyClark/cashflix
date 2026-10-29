from decimal import ROUND_HALF_UP, Decimal

from django.utils.translation import gettext as _


class RateNotFound(Exception):
    pass


def uah_rate(currency, on_date):
    from .models import ExchangeRate

    if currency == "UAH":
        return Decimal("1")

    rate = latest_rate(currency, on_date)
    if rate is None:
        rate = download_rate(currency, on_date)
    if rate is None:
        raise RateNotFound(_("Немає курсу %(currency)s на %(date)s") % {"currency": currency, "date": on_date})
    return rate


def convert_rate(currency, base_currency, on_date):
    if currency == base_currency:
        return Decimal("1")
    return uah_rate(currency, on_date) / uah_rate(base_currency, on_date)

def convert_amount(amount, source, target, on_date):
    if source == target:
        return amount
    return (amount * convert_rate(source, target, on_date)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def latest_rate(currency, on_date):
    from .models import ExchangeRate

    return (
        ExchangeRate.objects.filter(currency=currency, date__lte=on_date)
        .order_by("-date")
        .values_list("rate", flat=True)
        .first()
    )


def download_rate(currency, on_date):
    from .nbu import NbuUnavailable, save_rates

    try:
        return save_rates(on_date).get(currency)
    except NbuUnavailable:
        return None
