import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://api.monobank.ua"
CURRENCIES = {980: "UAH", 840: "USD", 978: "EUR"}
STATEMENT_PAUSE = 60
MAX_PERIOD = 31 * 24 * 3600


class MonobankError(Exception):
    pass


class MonobankAuthError(MonobankError):
    pass


class MonobankRateLimit(MonobankError):
    pass


def request(token, path):
    req = Request(BASE_URL + path, headers={"X-Token": token, "User-Agent": "CashFlix"})
    try:
        with urlopen(req, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code in (401, 403):
            raise MonobankAuthError("token") from error
        if error.code == 429:
            raise MonobankRateLimit("rate") from error
        raise MonobankError(str(error)) from error
    except (URLError, TimeoutError, ValueError) as error:
        raise MonobankError(str(error)) from error


def client_info(token):
    return request(token, "/personal/client-info")


def statement(token, account_id, since, until):
    return request(token, f"/personal/statement/{account_id}/{int(since)}/{int(until)}")
