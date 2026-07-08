from django.contrib import admin

from .models import Track


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ("name", "is_default", "scorer_role", "min_hourly_rate")
    list_filter = ("is_default",)
