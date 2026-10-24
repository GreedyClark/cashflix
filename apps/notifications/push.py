import json
import logging

from django.conf import settings
from pywebpush import WebPushException, webpush

log = logging.getLogger(__name__)
GONE = (404, 410)


def configured():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def send(subscription, title, body, url="/"):
    payload = json.dumps({"title": title, "body": body, "url": url})
    try:
        webpush(
            subscription_info=subscription.info(),
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            ttl=12 * 3600,
        )
    except WebPushException as error:
        status = getattr(error.response, "status_code", None)
        if status in GONE:
            subscription.delete()
        else:
            log.warning("Push failed: %s", error)
        return False
    return True


def send_all(user, title, body, url="/"):
    return sum(send(subscription, title, body, url) for subscription in user.push_subscriptions.all())
