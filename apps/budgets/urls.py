from django.urls import path

from . import views

app_name = "budgets"

urlpatterns = [
    path("budget/", views.budget, name="budget"),
    path("budget/limits/new/", views.limit_create, name="limit_create"),
    path("budget/limits/<int:pk>/", views.limit_edit, name="limit_edit"),
    path("budget/limits/<int:pk>/delete/", views.limit_delete, name="limit_delete"),
    path("budget/hints/", views.limit_hints, name="limit_hints"),
    path("budget/amount/", views.limit_amount, name="limit_amount"),
]
