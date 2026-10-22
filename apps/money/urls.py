from django.urls import path

from . import views

app_name = "money"

urlpatterns = [
    path("operations/", views.transaction_list, name="transactions"),
    path("operations/new/", views.transaction_create, name="transaction_create"),
    path("operations/<int:pk>/", views.transaction_edit, name="transaction_edit"),
    path("operations/<int:pk>/delete/", views.transaction_delete, name="transaction_delete"),
    path("operations/undo/", views.transaction_undo, name="transaction_undo"),
    path("wallet/", views.account_list, name="accounts"),
    path("wallet/new/", views.account_create, name="account_create"),
    path("wallet/<int:pk>/", views.account_edit, name="account_edit"),
    path("wallet/<int:pk>/archive/", views.account_archive, name="account_archive"),
    path("wallet/<int:pk>/valuation/", views.valuation_create, name="valuation_create"),
]
