from django.urls import path

from . import views

app_name = "households"

urlpatterns = [
    path("onboarding/", views.onboarding, name="onboarding"),
]