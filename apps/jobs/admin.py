from django.contrib import admin, messages

from .models import ClientProfile, JobPosting, SavedFilter


@admin.register(SavedFilter)
class SavedFilterAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "poll_interval_min", "require_verified_payment", "vibeworker_filter_id", "last_polled_at")
    list_filter = ("is_active", "require_verified_payment")
    search_fields = ("name", "vibeworker_filter_id")


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ("upwork_client_id", "risk_level", "verified_payment", "hire_rate", "total_spent", "country", "avg_rating")
    list_filter = ("verified_payment", "country")
    search_fields = ("upwork_client_id", "country")


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "budget_type", "budget_min", "budget_max", "proposals_bucket", "client", "posted_at")
    list_filter = ("status", "budget_type", "matched_filter")
    search_fields = ("title", "job_id")
    autocomplete_fields = ("client", "matched_filter")
    date_hierarchy = "posted_at"
    actions = ("skip_jobs", "return_to_feed")

    def _bulk_transition(self, request, queryset, target):
        ok = 0
        for job in queryset:
            try:
                job.transition_to(target)
                ok += 1
            except ValueError as exc:
                self.message_user(request, f"{job.job_id}: {exc}", level=messages.WARNING)
        self.message_user(request, f"Переведено: {ok}", level=messages.SUCCESS)

    @admin.action(description="Пропустить (→ skipped)")
    def skip_jobs(self, request, queryset):
        self._bulk_transition(request, queryset, JobPosting.Status.SKIPPED)

    @admin.action(description="Вернуть в ленту (skipped → new)")
    def return_to_feed(self, request, queryset):
        self._bulk_transition(request, queryset, JobPosting.Status.NEW)
