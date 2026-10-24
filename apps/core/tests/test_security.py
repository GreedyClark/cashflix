from django.urls import reverse


def test_security_headers(client, db):
    response = client.get(reverse("account_login"))

    csp = response["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_other_family_data_is_404(client, yura, user):
    from apps.households.services import create_household
    from apps.money.models import Account

    stranger = create_household(user, "Чужий дім")
    account = Account.objects.create(household=stranger, name="Чужа")
    category = stranger.categories.first()
    client.force_login(yura.user)

    for name, args in [
        ("money:account_edit", [account.pk]),
        ("money:category_edit", [category.pk]),
        ("money:valuation_create", [account.pk]),
    ]:
        assert client.get(reverse(name, args=args)).status_code == 404


def test_interface_stays_ukrainian_for_english_browser(client, yura):
    client.force_login(yura.user)
    response = client.get("/", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert response["Content-Language"] == "uk"
