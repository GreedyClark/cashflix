import json

from django.http import HttpResponse
from django.template.loader import render_to_string


def toast_response(request, message, undo_url=None, events=()):
    html = render_to_string("core/_toast.html", {"message": message, "undo_url": undo_url}, request=request)
    response = HttpResponse(html)
    response["HX-Reswap"] = "none"
    if events:
        response["HX-Trigger"] = json.dumps({name: True for name in events})
    return response