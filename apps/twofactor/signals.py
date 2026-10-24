from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .gate import SESSION_KEY


@receiver(user_logged_in)
def reset_second_factor(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        request.session.pop(SESSION_KEY, None)
