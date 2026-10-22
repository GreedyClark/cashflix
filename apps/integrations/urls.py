from django.urls import path

from . import api, views

app_name = "integrations"

urlpatterns = [
    path("api/shortcut/", api.shortcut, name="shortcut_api"),
    path("api/monobank/<str:secret>/", api.monobank_webhook, name="monobank_webhook"),
    path("connections/", views.connections, name="connections"),
    path("connections/token/", views.token_issue, name="token_issue"),
    path("connections/token/revoke/", views.token_revoke, name="token_revoke"),
    path("connections/monobank/", views.monobank_connect, name="monobank_connect"),
    path("connections/monobank/refresh/", views.monobank_refresh, name="monobank_refresh"),
    path("connections/monobank/links/", views.monobank_links, name="monobank_links"),
    path("connections/monobank/<int:pk>/sync/", views.monobank_sync, name="monobank_sync"),
    path("connections/monobank/webhook/", views.monobank_webhook_toggle, name="monobank_webhook_toggle"),
    path("connections/monobank/disconnect/", views.monobank_disconnect, name="monobank_disconnect"),
]
