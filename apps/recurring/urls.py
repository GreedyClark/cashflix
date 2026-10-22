from django.urls import path

from . import views

app_name = "recurring"

urlpatterns = [
    path("payments/", views.payment_list, name="payments"),
    path("payments/new/", views.payment_create, name="payment_create"),
    path("payments/<int:pk>/", views.payment_edit, name="payment_edit"),
    path("payments/<int:pk>/pay/", views.payment_pay, name="payment_pay"),
    path("payments/<int:pk>/toggle/", views.payment_toggle, name="payment_toggle"),
    path("payments/<int:pk>/delete/", views.payment_delete, name="payment_delete"),
]
