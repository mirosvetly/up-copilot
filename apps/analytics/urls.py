from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("analytics/", views.analytics, name="analytics"),
    path("metrics/", views.metrics_endpoint, name="metrics"),
]
