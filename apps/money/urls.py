from django.urls import path

from . import views

app_name = "money"

urlpatterns = [
    path("operations/", views.transaction_list, name="transactions"),
]