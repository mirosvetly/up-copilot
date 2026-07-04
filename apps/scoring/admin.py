from django.contrib import admin

from .models import JobScore


@admin.register(JobScore)
class JobScoreAdmin(admin.ModelAdmin):
    list_display = ("job", "score", "model_name", "reasoning", "updated_at")
    list_filter = ("model_name",)
    search_fields = ("job__title", "job__job_id")
