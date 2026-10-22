from django.urls import path

from . import category_views, views

app_name = "money"

urlpatterns = [
    path("operations/", views.transaction_list, name="transactions"),
    path("operations/export/", views.transaction_export, name="transaction_export"),
    path("operations/new/", views.transaction_create, name="transaction_create"),
    path("operations/<int:pk>/", views.transaction_edit, name="transaction_edit"),
    path("operations/<int:pk>/not-duplicate/", views.transaction_not_duplicate, name="transaction_not_duplicate"),
    path("operations/<int:pk>/delete/", views.transaction_delete, name="transaction_delete"),
    path("operations/undo/", views.transaction_undo, name="transaction_undo"),
    path("categories/", category_views.category_list, name="categories"),
    path("categories/new/", category_views.category_create, name="category_create"),
    path("categories/icons/", category_views.icon_grid, name="icon_grid"),
    path("categories/<int:pk>/", category_views.category_edit, name="category_edit"),
    path("categories/<int:pk>/archive/", category_views.category_archive, name="category_archive"),
    path("categories/<int:pk>/delete/", category_views.category_delete, name="category_delete"),
    path("categories/<int:pk>/merge/", category_views.category_merge, name="category_merge"),
    path("wallet/", views.account_list, name="accounts"),
    path("wallet/new/", views.account_create, name="account_create"),
    path("wallet/<int:pk>/", views.account_edit, name="account_edit"),
    path("wallet/<int:pk>/archive/", views.account_archive, name="account_archive"),
    path("wallet/<int:pk>/valuation/", views.valuation_create, name="valuation_create"),
]
