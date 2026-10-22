from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import gemini
from .briefing import build_briefing
from .models import AssistantKey, ChatMessage

DAILY_LIMIT = 30
HISTORY = 6
SUGGESTIONS = [
    "Де можна зекономити цього місяця?",
    "Чи вкладемось у ліміти?",
    "Як швидше накопичити на ціль?",
    "Що змінилось порівняно з минулим місяцем?",
]


def asked_today(membership):
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return membership.chat_messages.filter(role=ChatMessage.Role.USER, created_at__gte=start).count()


def assistant(request):
    key = AssistantKey.objects.filter(membership=request.membership).first()
    if key is None:
        return render(request, "assistant/setup.html")
    context = {
        "key": key,
        "chat": request.membership.chat_messages.all(),
        "suggestions": SUGGESTIONS,
        "left_today": max(0, DAILY_LIMIT - asked_today(request.membership)),
        "briefing": build_briefing(request.household, timezone.localdate()),
    }
    return render(request, "assistant/chat.html", context)


@require_POST
def key_save(request):
    raw = request.POST.get("gemini_key", "").strip()
    if not raw:
        messages.error(request, _("Вставте ключ Gemini."))
        return redirect("assistant:assistant")
    try:
        gemini.check_key(raw)
    except gemini.BadKey:
        messages.error(request, _("Google не прийняв ключ. Перевірте, що скопіювали його повністю."))
        return redirect("assistant:assistant")
    except gemini.AssistantError:
        messages.error(request, _("Не вдалося перевірити ключ: Google зараз недоступний. Спробуйте пізніше."))
        return redirect("assistant:assistant")
    key = AssistantKey.objects.filter(membership=request.membership).first() or AssistantKey(membership=request.membership)
    key.key = raw
    key.save()
    messages.success(request, _("Асистента підключено."))
    return redirect("assistant:assistant")


@require_POST
def disable(request):
    AssistantKey.objects.filter(membership=request.membership).delete()
    request.membership.chat_messages.all().delete()
    messages.success(request, _("Асистента вимкнено, ключ і історію чату видалено."))
    return redirect("assistant:assistant")


@require_POST
def clear(request):
    request.membership.chat_messages.all().delete()
    return redirect("assistant:assistant")


@require_POST
def ask(request):
    key = AssistantKey.objects.filter(membership=request.membership).first()
    question = request.POST.get("question", "").strip()[:500]
    if key is None or not question:
        return render(request, "assistant/_exchange.html", {"skip": True})
    if asked_today(request.membership) >= DAILY_LIMIT:
        return render(request, "assistant/_exchange.html", {"question": question, "error": _("На сьогодні запити закінчились, повертайтесь завтра.")})

    history = list(request.membership.chat_messages.order_by("-created_at", "-pk")[:HISTORY])[::-1]
    briefing = build_briefing(request.household, timezone.localdate())
    try:
        answer = gemini.generate(key.key, briefing, history, question)
    except gemini.BadKey:
        error = _("Google не приймає ваш ключ. Додайте новий: вимкніть і знову підключіть асистента.")
    except gemini.QuotaExceeded:
        error = _("Безкоштовний ліміт Google на зараз вичерпано. Спробуйте за хвилину.")
    except gemini.AssistantError:
        error = _("Gemini зараз не відповідає. Спробуйте трохи пізніше.")
    else:
        error = None
    if error:
        return render(request, "assistant/_exchange.html", {"question": question, "error": error})

    ChatMessage.objects.create(membership=request.membership, role=ChatMessage.Role.USER, text=question)
    reply = ChatMessage.objects.create(
        membership=request.membership, role=ChatMessage.Role.ASSISTANT, text=answer or _("Не вийшло сформулювати відповідь.")
    )
    context = {
        "question": question,
        "reply": reply,
        "left_today": max(0, DAILY_LIMIT - asked_today(request.membership)),
    }
    return render(request, "assistant/_exchange.html", context)
