from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("analytics/", views.analytics, name="analytics"),
    path("metrics/", views.metrics_endpoint, name="metrics"),
    path("analytics/money/", views.money_add, name="money_add"),
    path("analytics/money/<int:pk>/delete/", views.money_delete, name="money_delete"),
]
