from django.urls import path

from . import views

app_name = "assistant"

urlpatterns = [
    path("assistant/", views.assistant, name="assistant"),
    path("assistant/key/", views.key_save, name="key_save"),
    path("assistant/ask/", views.ask, name="ask"),
    path("assistant/clear/", views.clear, name="clear"),
    path("assistant/disable/", views.disable, name="disable"),
]
