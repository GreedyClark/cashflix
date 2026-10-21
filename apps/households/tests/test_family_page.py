import datetime
from decimal import Decimal

from django.urls import reverse

from apps.households.services import month_spending
from apps.money.models import Transaction

OCT_20 = datetime.date(2026, 10, 20)


def spend(home, account, amount, member=None, date=OCT_20):
    Transaction.objects.create(
        household=home, account=account, member=member, amount=Decimal(amount), date=date, title="Покупка"
    )


def test_month_spending_splits_by_member(home, mono, yura, olya):
    spend(home, mono, "600", member=yura)
    spend(home, mono, "300", member=olya)
    spend(home, mono, "100")
    spend(home, mono, "999", member=yura, date=datetime.date(2026, 9, 30))

    summary = month_spending(home, today=OCT_20)

    assert summary["total"] == Decimal("1000")
    assert [s["percent"] for s in summary["segments"]] == [60, 30, 10]
    assert [m.operations for m in summary["memberships"]] == [1, 1]


def test_family_page_shows_members_and_invite(auth_client, user):
    response = auth_client.get(reverse("households:members"))
    html = response.content.decode()

    assert response.status_code == 200
    assert user.email in html
    assert "Запросити в сім'ю" in html
    assert "Цього місяця витрат ще немає" in html