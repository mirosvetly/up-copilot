from django.urls import path

from . import views

app_name = "screening"

urlpatterns = [
    path("job/<int:pk>/screening/generate/", views.generate, name="generate"),
    path("job/<int:pk>/screening/save/", views.save, name="save"),
]
