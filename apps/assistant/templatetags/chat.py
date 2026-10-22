import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()
BOLD = re.compile(r"\*\*(.+?)\*\*")
BULLET = re.compile(r"^\s*[-*•]\s+")


@register.filter
def chat_markdown(text):
    html, items = [], []
    for raw in (text or "").splitlines():
        line = BOLD.sub(r"<b>\1</b>", escape(raw.strip()))
        if BULLET.match(raw):
            items.append(f"<li>{BULLET.sub('', line)}</li>")
            continue
        if items:
            html.append(f"<ul>{''.join(items)}</ul>")
            items = []
        if line:
            html.append(f"<p>{line}</p>")
    if items:
        html.append(f"<ul>{''.join(items)}</ul>")
    return mark_safe("".join(html))
