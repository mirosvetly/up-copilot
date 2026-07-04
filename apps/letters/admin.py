from django.contrib import admin

from .models import CoverLetterDraft


@admin.register(CoverLetterDraft)
class CoverLetterDraftAdmin(admin.ModelAdmin):
    list_display = ("job", "version", "is_active", "model_name", "updated_at")
    list_filter = ("is_active", "model_name")
    search_fields = ("job__title", "job__job_id")
