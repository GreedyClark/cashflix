from django.urls import path

from . import views

app_name = "goals"

urlpatterns = [
    path("goals/", views.goal_list, name="goals"),
    path("goals/new/", views.goal_create, name="goal_create"),
    path("goals/<int:pk>/", views.goal_edit, name="goal_edit"),
    path("goals/<int:pk>/archive/", views.goal_archive, name="goal_archive"),
    path("goals/<int:pk>/delete/", views.goal_delete, name="goal_delete"),
    path("goals/<int:pk>/add/", views.contribution_create, name="contribution_create"),
    path("goals/contributions/<int:pk>/", views.contribution_edit, name="contribution_edit"),
    path("goals/contributions/<int:pk>/delete/", views.contribution_delete, name="contribution_delete"),
]
