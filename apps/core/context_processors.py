from django.conf import settings
from django.urls import reverse

from .navigation import MAIN_MENU


def navigation(request):
    current = request.resolver_match.view_name if request.resolver_match else None
    items = []
    for item in MAIN_MENU:
        url_name = item["url_name"]
        items.append({
            **item,
            "url": reverse(url_name) if url_name else None,
            "active": url_name is not None and url_name == current,
        })
    return {"main_menu": items}


def demo(request):
    return {"demo_login": settings.DEBUG}
