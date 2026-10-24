from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("apps.households.urls")),
    path("", include("apps.money.urls")),
    path("", include("apps.budgets.urls")),
    path("", include("apps.recurring.urls")),
    path("", include("apps.goals.urls")),
    path("", include("apps.integrations.urls")),
    path("", include("apps.assistant.urls")),
    path("", include("apps.twofactor.urls")),
    path("", include("apps.notifications.urls")),
    path("", include("apps.core.urls")),
]
