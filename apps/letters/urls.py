from django.urls import path

from . import views

app_name = "letters"

urlpatterns = [
    path("job/<int:pk>/cover/generate/", views.generate, name="generate"),
    path("job/<int:pk>/cover/save/", views.save, name="save"),
]
