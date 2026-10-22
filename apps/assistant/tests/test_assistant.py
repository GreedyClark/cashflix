import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.assistant import gemini, views
from apps.assistant.briefing import build_briefing
from apps.assistant.models import AssistantKey, ChatMessage
from apps.assistant.templatetags.chat import chat_markdown
from apps.budgets.models import Limit
from apps.goals.models import Goal
from apps.money.models import Transaction

TODAY = datetime.date(2026, 10, 20)


@pytest.fixture
def fake_gemini(monkeypatch):
    calls = []

    def generate(key, briefing, history, question):
        calls.append({"key": key, "briefing": briefing, "history": history, "question": question})
        return "**Кафе** зросло.\n- Порада одна\n- Порада дві"

    monkeypatch.setattr(gemini, "generate", generate)
    monkeypatch.setattr(gemini, "check_key", lambda key: None)
    return calls


@pytest.fixture
def yura_client(client, yura):
    client.force_login(yura.user)
    return client


@pytest.fixture
def with_key(yura):
    key = AssistantKey(membership=yura)
    key.key = "AIzaTestKey1234"
    key.save()
    return key


def test_briefing_has_numbers_but_no_private_details(home, mono, food, yura):
    Transaction.objects.create(
        household=home, account=mono, category=food, member=yura, amount=Decimal("486"), title="Сільпо Оболонь",
        date=TODAY, note="купив маму подарунок",
    )
    Limit.objects.create(household=home, category=food, amount=Decimal("1000"))
    Goal.objects.create(household=home, name="Відпустка", target_amount=Decimal("60000"), account=mono)

    text = build_briefing(home, TODAY)

    assert "Продукти" in text
    assert "486\xa0₴" in text
    assert "Відпустка" in text
    for private in ("Сільпо", "Оболонь", "маму", mono.name, yura.user.name, yura.user.email):
        assert private not in text


def test_setup_screen_without_key(yura_client):
    response = yura_client.get(reverse("assistant:assistant"))

    assert "assistant/setup.html" in [t.name for t in response.templates]
    assert "без назв магазинів, імен і рахунків" in response.content.decode()


def test_save_key_encrypted(yura_client, yura, fake_gemini):
    yura_client.post(reverse("assistant:key_save"), {"gemini_key": "AIzaSecret9876"})

    key = AssistantKey.objects.get(membership=yura)
    assert key.key == "AIzaSecret9876"
    assert "Secret" not in key.key_encrypted
    assert key.hint == "9876"


def test_bad_key_is_not_saved(yura_client, yura, monkeypatch):
    def reject(key):
        raise gemini.BadKey("nope")

    monkeypatch.setattr(gemini, "check_key", reject)

    response = yura_client.post(reverse("assistant:key_save"), {"gemini_key": "wrong"}, follow=True)

    assert "не прийняв ключ" in response.content.decode()
    assert not AssistantKey.objects.exists()


def test_ask_saves_exchange_and_uses_own_key(yura_client, yura, with_key, fake_gemini):
    response = yura_client.post(reverse("assistant:ask"), {"question": "Де зекономити?"})

    assert fake_gemini[0]["key"] == "AIzaTestKey1234"
    assert fake_gemini[0]["question"] == "Де зекономити?"
    assert list(yura.chat_messages.values_list("role", flat=True)) == ["user", "model"]
    assert "<b>Кафе</b>" in response.content.decode()


def test_history_is_sent_back(yura_client, yura, with_key, fake_gemini):
    yura_client.post(reverse("assistant:ask"), {"question": "Перше"})
    yura_client.post(reverse("assistant:ask"), {"question": "Друге"})

    assert [m.text for m in fake_gemini[1]["history"]][0] == "Перше"


def test_other_member_has_no_access_to_my_key(client, olya, with_key, fake_gemini):
    client.force_login(olya.user)

    response = client.post(reverse("assistant:ask"), {"question": "Привіт"})

    assert fake_gemini == []
    assert not ChatMessage.objects.exists()
    assert response.content.strip() == b""


def test_daily_limit(yura_client, yura, with_key, fake_gemini, monkeypatch):
    monkeypatch.setattr(views, "DAILY_LIMIT", 1)
    yura_client.post(reverse("assistant:ask"), {"question": "Раз"})

    response = yura_client.post(reverse("assistant:ask"), {"question": "Два"})

    assert "закінчились" in response.content.decode()
    assert len(fake_gemini) == 1


def test_gemini_error_is_friendly(yura_client, with_key, monkeypatch):
    def fail(*args):
        raise gemini.QuotaExceeded("429")

    monkeypatch.setattr(gemini, "generate", fail)

    response = yura_client.post(reverse("assistant:ask"), {"question": "Привіт"})

    assert "ліміт Google" in response.content.decode()
    assert not ChatMessage.objects.exists()


def test_disable_removes_key_and_history(yura_client, yura, with_key, fake_gemini):
    yura_client.post(reverse("assistant:ask"), {"question": "Привіт"})

    yura_client.post(reverse("assistant:disable"))

    assert not AssistantKey.objects.exists()
    assert not ChatMessage.objects.exists()


def test_chat_markdown_escapes_html():
    html = chat_markdown("<script>x</script>\n**жирний**\n- пункт")

    assert "<script>" not in html
    assert "<b>жирний</b>" in html
    assert "<ul><li>пункт</li></ul>" in html


def test_translate_errors():
    class Fake(Exception):
        def __init__(self, code, text=""):
            super().__init__(text)
            self.code = code

    assert isinstance(gemini.translate(Fake(403)), gemini.BadKey)
    assert isinstance(gemini.translate(Fake(400, "API key not valid")), gemini.BadKey)
    assert isinstance(gemini.translate(Fake(429)), gemini.QuotaExceeded)
    assert type(gemini.translate(Fake(500))) is gemini.AssistantError
