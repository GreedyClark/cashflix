import json
from decimal import Decimal
from urllib.error import URLError
from urllib.request import urlopen

URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?date={date}&json"
CURRENCIES = ("USD", "EUR")


class NbuUnavailable(Exception):
    pass


def fetch(on_date):
    try:
        with urlopen(URL.format(date=on_date.strftime("%Y%m%d")), timeout=5) as response:
            rows = json.load(response)
    except (URLError, TimeoutError, ValueError) as error:
        raise NbuUnavailable(str(error)) from error
    return {row["cc"]: Decimal(str(row["rate"])) for row in rows if row.get("cc") in CURRENCIES}


def save_rates(on_date):
    from .models import ExchangeRate

    rates = fetch(on_date)
    for currency, rate in rates.items():
        ExchangeRate.objects.update_or_create(currency=currency, date=on_date, defaults={"rate": rate})
    return rates
