from django.urls import path

from . import views

app_name = "jobs"

urlpatterns = [
    path("", views.feed, name="feed"),
    path("sent/", views.feed, {"sent": True}, name="sent"),
    path("refresh/", views.refresh, name="refresh"),
    path("score-status/", views.score_status, name="score_status"),
    path("skip-all/", views.skip_all, name="skip_all"),
    path("job/<int:pk>/", views.detail, name="detail"),
    path("job/<int:pk>/tr-status/", views.tr_status, name="tr_status"),
    path("job/<int:pk>/toggle-keyword/", views.toggle_keyword, name="toggle_keyword"),
    path("job/<int:pk>/tracking/", views.job_tracking, name="job_tracking"),
    path("webhooks/vollna/", views.vollna_webhook, name="vollna_webhook"),
    path("job/<int:pk>/<str:action>/", views.job_action, name="job_action"),
]
