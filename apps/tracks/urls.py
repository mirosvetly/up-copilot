from django.urls import path

from . import views

app_name = "tracks"

urlpatterns = [
    path("settings/tracks/", views.track_list, name="list"),
    path("settings/tracks/new/", views.track_edit, name="create"),
    path("settings/tracks/<int:pk>/", views.track_edit, name="edit"),
]
