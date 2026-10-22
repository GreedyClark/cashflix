from django.conf import settings
from google import genai
from google.genai import errors, types

SYSTEM = """Ти фінансовий помічник у застосунку сімейного бюджету CashFlix.
Відповідай українською, коротко й по суті: до 120 слів, за потреби короткий список.
Використовуй лише числа з довідки нижче. Нічого не вигадуй і не рахуй заново те, що вже пораховано.
Якщо в довідці немає даних для відповіді, так і скажи.
Суми пиши як «22 189 ₴». Не давай інвестиційних порад щодо конкретних цінних паперів.
Якщо питання не про бюджет цієї сім'ї, ввічливо відмов і запропонуй спитати про витрати, ліміти чи цілі.

Довідка CashFlix:
{briefing}"""


class AssistantError(Exception):
    pass


class BadKey(AssistantError):
    pass


class QuotaExceeded(AssistantError):
    pass


def model_name():
    return getattr(settings, "GEMINI_MODEL", "") or "gemini-flash-latest"


def translate(error):
    code = getattr(error, "code", None)
    if code in (401, 403) or (code == 400 and "API key" in str(error)):
        return BadKey(str(error))
    if code == 429:
        return QuotaExceeded(str(error))
    return AssistantError(str(error))


def check_key(key):
    try:
        with genai.Client(api_key=key) as client:
            client.models.get(model=model_name())
    except errors.APIError as error:
        raise translate(error) from error
    except Exception as error:
        raise AssistantError(str(error)) from error


def generate(key, briefing, history, question):
    contents = [
        types.Content(role=message.role, parts=[types.Part(text=message.text)]) for message in history
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
    config = types.GenerateContentConfig(system_instruction=SYSTEM.format(briefing=briefing), temperature=0.4)
    try:
        with genai.Client(api_key=key) as client:
            response = client.models.generate_content(model=model_name(), contents=contents, config=config)
    except errors.APIError as error:
        raise translate(error) from error
    except Exception as error:
        raise AssistantError(str(error)) from error
    return (response.text or "").strip()
