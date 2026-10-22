from django.urls import path

from . import views

app_name = "households"

urlpatterns = [
    path("onboarding/", views.onboarding, name="onboarding"),
    path("family/", views.members, name="members"),
    path("family/invitation/", views.invitation_create, name="invitation_create"),
    path("family/invitation/revoke/", views.invitation_revoke, name="invitation_revoke"),
    path("family/members/<int:pk>/remove/", views.member_remove, name="member_remove"),
    path("family/leave/", views.leave, name="leave"),
    path("family/<int:pk>/switch/", views.switch, name="switch"),
    path("join/<str:token>/", views.join, name="join"),
]