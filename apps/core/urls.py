from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("demo/", views.demo_login, name="demo_login"),
    path("health/", views.health, name="health"),
]