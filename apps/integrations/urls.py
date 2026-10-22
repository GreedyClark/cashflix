from django.urls import path

from . import api, views

app_name = "integrations"

urlpatterns = [
    path("api/shortcut/", api.shortcut, name="shortcut_api"),
    path("connections/", views.connections, name="connections"),
    path("connections/token/", views.token_issue, name="token_issue"),
    path("connections/token/revoke/", views.token_revoke, name="token_revoke"),
]
