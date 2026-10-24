from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.core.templatetags.money import money
from apps.money.rates import RateNotFound
from apps.recurring.models import RecurringPayment
from apps.twofactor import telegram
from apps.twofactor.models import SecondFactor

from . import push
from .models import NotifySettings, PushSubscription


@dataclass
class Item:
    payment: RecurringPayment
    days: int

    @property
    def when(self):
        if self.days < 0:
            return f"Прострочено {-self.days} дн."
        if self.days == 0:
            return "Сьогодні"
        if self.days == 1:
            return "Завтра"
        return f"Через {self.days} дн."

    @property
    def amount(self):
        payment = self.payment
        text = money(payment.amount, payment.pay_currency)
        if payment.is_approximate:
            text = "≈ " + text
        if payment.is_foreign:
            try:
                text += f" (≈ {money(payment.account_amount(timezone.localdate()), payment.account.currency)})"
            except RateNotFound:
                pass
        return text

    @property
    def can_pay(self):
        return self.payment.is_manual and self.days <= 1

    def line(self):
        return f"{self.when}: {self.payment.title} — {self.amount}"


def payments_for(user):
    memberships = user.memberships.active()
    return (
        RecurringPayment.objects.filter(is_active=True, household__memberships__in=memberships)
        .filter(Q(member__in=memberships) | Q(member__isnull=True))
        .select_related("account", "household", "category")
        .distinct()
    )


def due_items(user, today):
    items = []
    for payment in payments_for(user):
        days = (payment.next_date - today).days
        reminders = payment.reminders or []
        overdue = payment.is_manual and days < 0 and reminders
        if days in reminders or overdue or payment.remind_on == today:
            items.append(Item(payment, days))
    return sorted(items, key=lambda item: item.days)


def telegram_text(items):
    lines = ["🔔 <b>Нагадування про платежі</b>", ""]
    lines += [f"<b>{item.when}</b>: {item.payment.title} — {item.amount}" for item in items]
    return "\n".join(lines)


def telegram_buttons(items):
    rows = []
    for item in items:
        if item.can_pay:
            payment = item.payment
            rows.append([
                {"text": f"✅ Оплатив: {payment.title}"[:40], "callback_data": f"pay:{payment.pk}:{payment.next_date:%Y%m%d}"},
                {"text": "⏰ Завтра", "callback_data": f"snooze:{payment.pk}"},
            ])
    return rows


def push_text(items):
    if len(items) == 1:
        item = items[0]
        return f"{item.when} оплатити", f"{item.payment.title} · {item.amount}"
    return f"Платежі: {len(items)} нагадування", "\n".join(item.line() for item in items[:4])


def deliver(user, items, chat_id):
    sent = 0
    if chat_id:
        try:
            telegram.send(chat_id, telegram_text(items), rows=telegram_buttons(items))
            sent += 1
        except telegram.TelegramError:
            pass
    if push.configured():
        title, body = push_text(items)
        sent += push.send_all(user, title, body, reverse("core:home"))
    return sent


def recipients():
    User = get_user_model()
    linked = SecondFactor.objects.filter(telegram_chat_id__isnull=False).values("user")
    pushing = PushSubscription.objects.values("user")
    return User.objects.filter(Q(pk__in=linked) | Q(pk__in=pushing), is_active=True)


def send_reminders(now=None):
    now = timezone.localtime(now)
    today = now.date()
    count = 0
    for user in recipients():
        notify = NotifySettings.of(user)
        if notify.last_sent_on == today or now.time() < notify.remind_at:
            continue
        notify.last_sent_on = today
        notify.save(update_fields=["last_sent_on"])
        items = due_items(user, today)
        if not items:
            continue
        factor = SecondFactor.objects.filter(user=user).first()
        chat_id = factor.telegram_chat_id if factor and notify.telegram else None
        if deliver(user, items, chat_id):
            count += 1
    return count
