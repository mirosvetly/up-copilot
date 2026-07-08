from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.letters.urls")),
    path("", include("apps.screening.urls")),
    path("", include("apps.analytics.urls")),
    path("", include("apps.tracks.urls")),
    path("", include("apps.jobs.urls")),
]
