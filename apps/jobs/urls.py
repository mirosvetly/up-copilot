from django.urls import path

from . import views

app_name = "jobs"

urlpatterns = [
    path("", views.feed, name="feed"),
    path("job/<int:pk>/", views.detail, name="detail"),
    path("job/<int:pk>/<str:action>/", views.job_action, name="job_action"),
]
