from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("notifications/", views.notify_settings, name="settings"),
    path("notifications/push/", views.subscribe, name="subscribe"),
    path("notifications/push/<int:pk>/delete/", views.unsubscribe, name="unsubscribe"),
    path("notifications/test/", views.test, name="test"),
    path("notifications/now/", views.remind_now, name="remind_now"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
]
