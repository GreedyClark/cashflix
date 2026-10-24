from django.urls import path

from . import views

app_name = "twofactor"

urlpatterns = [
    path("security/", views.security, name="security"),
    path("security/method/", views.choose, name="choose"),
    path("security/telegram/", views.telegram_link, name="telegram"),
    path("security/telegram/status/", views.telegram_link_status, name="telegram_status"),
    path("security/totp/", views.totp_setup, name="totp"),
    path("security/codes/", views.new_codes, name="new_codes"),
    path("security/devices/<int:pk>/forget/", views.forget_device, name="forget_device"),
    path("security/confirm/", views.confirm, name="confirm"),
    path("security/confirm/status/", views.confirm_status, name="confirm_status"),
    path("security/confirm/backup/", views.confirm_backup, name="confirm_backup"),
    path("api/telegram/", views.telegram_webhook, name="telegram_webhook"),
]
