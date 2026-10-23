import json

from django.contrib.auth.decorators import login_not_required
from django.db import transaction as db_transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.money.forms import default_account
from apps.money.ingest import ingest
from apps.money.models import Account, Transaction
from apps.money.rates import RateNotFound

from .models import MonobankAccount, MonobankConnection, ShortcutToken
from .parsing import BadPayload, match_account, parse_amount, parse_moment
from .sync import minor, process_item, reconcile

MESSAGES = {
    "amount": "Не вдалося прочитати суму.",
    "time": "Не вдалося прочитати час операції.",
    "account": "У сім'ї немає рахунку для цієї картки.",
    "rate": "Немає курсу валюти на цю дату.",
}


def error(code, status=400):
    return JsonResponse({"status": "error", "error": code, "message": MESSAGES.get(code, code)}, status=status)


def read_token(request, payload):
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return str(payload.get("token", "")).strip()


@csrf_exempt
@login_not_required
@require_POST
def shortcut(request):
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        payload = request.POST.dict()
    if not isinstance(payload, dict):
        return error("payload")

    token = ShortcutToken.objects.find(read_token(request, payload))
    if token is None:
        return JsonResponse({"status": "error", "error": "token", "message": "Невірний токен."}, status=401)
    membership = token.membership
    household = membership.household

    try:
        amount = parse_amount(payload.get("amount"))
        moment = parse_moment(payload.get("time"))
    except BadPayload as problem:
        return error(str(problem))

    accounts = list(household.accounts.filter(is_archived=False).exclude(kind=Account.Kind.INVESTMENT))
    fallback = token.account if token.account and not token.account.is_archived else default_account(household, membership)
    account = match_account(accounts, payload.get("card"), fallback)
    if account is None:
        return error("account")
    if MonobankAccount.objects.filter(account=account).exists():
        return JsonResponse({
            "status": "skipped",
            "message": f"{account.name} підключено до Monobank, операція прийде звідти.",
        })

    kind = Transaction.Type.INCOME if str(payload.get("type", "")).lower() in ("income", "дохід") else Transaction.Type.EXPENSE
    title = str(payload.get("merchant") or payload.get("title") or "").strip() or "Apple Pay"
    try:
        tx, status = ingest(
            household,
            account=account,
            amount=amount,
            title=title,
            source=Transaction.Source.SHORTCUT,
            occurred_at=moment,
            external_id=str(payload.get("id") or "")[:64],
            member=membership,
            kind=kind,
        )
    except RateNotFound:
        return error("rate")
    token.touch()

    return JsonResponse({
        "status": status,
        "id": tx.pk,
        "title": tx.title,
        "amount": str(tx.amount),
        "currency": tx.currency,
        "account": tx.account.name,
        "category": tx.category.name if tx.category else "",
        "review": tx.needs_review,
        "message": summary(tx, status),
    }, status=201 if status == "created" else 200)


def summary(tx, status):
    if status == "duplicate":
        return f"Вже записано: {tx.title}"
    category = tx.category.name if tx.category else ""
    text = f"{tx.title} · {tx.amount} {tx.currency} · {category}"
    if tx.needs_review:
        text += " (перевірте категорію)"
    if tx.duplicate_of_id:
        text += " · можливий дубль"
    return text


@csrf_exempt
@login_not_required
def monobank_webhook(request, secret):
    connection = MonobankConnection.objects.filter(webhook_secret=secret).exclude(webhook_secret="").first()
    if connection is None:
        return JsonResponse({"status": "unknown"}, status=404)
    if request.method != "POST":
        return JsonResponse({"status": "ok"})
    try:
        payload = json.loads(request.body or b"{}")
        data = payload["data"]
        item = data["statementItem"]
        mono_id = data["account"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"status": "ignored"})
    mono_account = connection.accounts.filter(mono_id=mono_id, account__isnull=False).select_related(
        "account__household", "connection__membership"
    ).first()
    if mono_account is None:
        return JsonResponse({"status": "ignored"})
    try:
        with db_transaction.atomic():
            status = process_item(mono_account, item)
            if item.get("balance") is not None:
                mono_account.balance = minor(item["balance"])
                mono_account.save(update_fields=["balance"])
                reconcile(mono_account, mono_account.balance)
    except RateNotFound:
        return JsonResponse({"status": "error"})
    return JsonResponse({"status": status})
