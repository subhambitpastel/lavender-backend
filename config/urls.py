from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

from apps.core.views import serve_media

urlpatterns = [
    path("", lambda request: redirect("dashboard:home")),
    path("django-admin/", admin.site.urls),
    path("api/v1/", include("apps.api.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    # Media is stored in the database, so serve it from there (dev and prod).
    path("media/<path:path>", serve_media, name="media"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
