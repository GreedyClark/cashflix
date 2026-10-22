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


def request(token, path, payload=None):
    headers = {"X-Token": token, "User-Agent": "CashFlix"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = Request(BASE_URL + path, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urlopen(req, timeout=10) as response:
            body = response.read()
            return json.loads(body) if body.strip() else {}
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


def set_webhook(token, url):
    return request(token, "/personal/webhook", {"webHookUrl": url})
