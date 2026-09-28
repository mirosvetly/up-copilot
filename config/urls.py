from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),  # set_language view
    path("", include("apps.letters.urls")),
    path("", include("apps.screening.urls")),
    path("", include("apps.analytics.urls")),
    path("", include("apps.tracks.urls")),
    path("", include("apps.jobs.urls")),
]
