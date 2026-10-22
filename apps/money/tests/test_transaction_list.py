import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.households.services import create_household
from apps.money.models import Transaction

URL = reverse("money:transactions")
OCTOBER = {"month": "2026-10"}


def add(home, account, title, amount, date=datetime.date(2026, 10, 14), **fields):
    return Transaction.objects.create(
        household=home, account=account, title=title, amount=Decimal(amount), date=date, **fields
    )


@pytest.fixture
def yura_client(client, yura):
    client.force_login(yura.user)
    return client


@pytest.fixture
def october(home, mono, food, salary, yura, olya):
    add(home, mono, "Сільпо", "500", category=food, member=yura)
    add(home, mono, "АТБ", "200", datetime.date(2026, 10, 15), category=food, member=olya)
    add(home, mono, "Ринок", "100", datetime.date(2026, 10, 15), category=food)
    add(home, mono, "Зарплата", "30000", datetime.date(2026, 10, 10), type="income", category=salary, member=yura)
    add(home, mono, "Старе", "999", datetime.date(2026, 9, 30), category=food, member=yura)


def titles(response):
    return [tx.title for day in response.context["days"] for tx in day["items"]]


def test_month_is_grouped_by_day_with_totals(yura_client, october):
    response = yura_client.get(URL, OCTOBER)

    assert response.status_code == 200
    assert titles(response) == ["Ринок", "АТБ", "Сільпо", "Зарплата"]
    assert response.context["days"][0]["spent"] == Decimal("300")
    assert response.context["spent"] == Decimal("800")
    assert response.context["earned"] == Decimal("30000")


def test_filters_by_type_member_and_shared(yura_client, october, olya):
    assert titles(yura_client.get(URL, {**OCTOBER, "type": "income"})) == ["Зарплата"]
    assert titles(yura_client.get(URL, {**OCTOBER, "member": olya.pk})) == ["АТБ"]
    assert titles(yura_client.get(URL, {**OCTOBER, "member": "shared"})) == ["Ринок"]


def test_search_ignores_case_of_cyrillic(yura_client, october):
    assert titles(yura_client.get(URL, {**OCTOBER, "q": "сільпо"})) == ["Сільпо"]


def test_other_month(yura_client, october):
    assert titles(yura_client.get(URL, {"month": "2026-09"})) == ["Старе"]


def test_htmx_request_gets_only_results(yura_client, october):
    response = yura_client.get(URL, OCTOBER, headers={"HX-Request": "true"})
    html = response.content.decode()

    assert "<html" not in html
    assert "Сільпо" in html


def test_other_family_data_is_invisible(yura_client, october, olya):
    stranger = create_household(olya.user, "Чужий дім")
    account = stranger.accounts.create(name="Чужа картка")
    category = stranger.categories.get(name="Продукти")
    add(stranger, account, "Чужа покупка", "50", category=category)

    assert "Чужа покупка" not in titles(yura_client.get(URL, OCTOBER))
    response = yura_client.get(URL, {**OCTOBER, "category": category.pk})
    assert "Чужа покупка" not in titles(response)


def test_empty_family_sees_empty_state(auth_client):
    response = auth_client.get(URL)

    assert "Операцій ще немає" in response.content.decode()


def test_day_filter_keeps_month_chart(yura_client, october):
    response = yura_client.get(URL, {**OCTOBER, "day": 15})

    assert titles(response) == ["Ринок", "АТБ"]
    bars = response.context["bars"]
    assert len(bars) == 31
    assert bars[13]["amount"] == Decimal("500")
    assert bars[14]["is_selected"]


def test_wrong_day_is_ignored(yura_client, october):
    response = yura_client.get(URL, {"month": "2026-02", "day": 31})

    assert response.status_code == 200
    assert response.context["selected_day"] is None