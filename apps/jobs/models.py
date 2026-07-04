from django.db import models

from apps.core.models import TimeStampedModel


class SavedFilter(TimeStampedModel):
    """A stored search the collector polls on its own cadence."""

    name = models.CharField(max_length=120)
    keywords = models.JSONField(default=list, blank=True)
    categories = models.JSONField(default=list, blank=True)
    min_budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    require_verified_payment = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    poll_interval_min = models.PositiveSmallIntegerField(default=15)
    last_polled_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name


class ClientProfile(TimeStampedModel):
    """The Upwork client that posts a job. Risk is derived, not stored."""

    upwork_client_id = models.CharField(max_length=64, unique=True)
    verified_payment = models.BooleanField(default=False)
    hire_rate = models.PositiveSmallIntegerField(null=True, blank=True)  # 0-100 %
    total_spent = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    country = models.CharField(max_length=80, blank=True)
    avg_rating = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True)  # 0-5
    total_jobs = models.PositiveIntegerField(null=True, blank=True)
    total_hires = models.PositiveIntegerField(null=True, blank=True)
    member_since = models.DateField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.upwork_client_id} ({self.country or '?'})"

    @property
    def risk_level(self) -> str:
        """low / med / high — the risk banner in the client card is derived, not stored."""
        if not self.verified_payment or (self.total_spent is not None and self.total_spent == 0):
            return "high"
        hr = self.hire_rate or 0
        if hr >= 70 and (self.total_spent or 0) >= 20000:
            return "low"
        return "med"


class JobPosting(TimeStampedModel):
    """Raw Upwork job + its position in the review status machine.

    Status flow (canonical, from the brief):
        new -> scored -> drafted -> reviewed -> applied
        any active state -> skipped / expired
        skipped -> new  (returned to the feed)
    Scoring/drafting fields (JobScore, CoverLetterDraft, ...) arrive in later
    phases as their own models; Phase 1 only collects and tracks status.
    """

    class Status(models.TextChoices):
        NEW = "new", "Новая"
        SCORED = "scored", "Оценена"
        DRAFTED = "drafted", "Черновик готов"
        REVIEWED = "reviewed", "Одобрена"
        APPLIED = "applied", "Отправлена"
        SKIPPED = "skipped", "Пропущена"
        EXPIRED = "expired", "Устарела"

    class BudgetType(models.TextChoices):
        HOURLY = "hourly", "Почасовая"
        FIXED = "fixed", "Фикс"

    ALLOWED_TRANSITIONS = {
        # scored -> reviewed is a shortcut: approving before the letters/draft
        # phase exists. Once drafting is built, the normal path is scored ->
        # drafted -> reviewed; both stay valid.
        Status.NEW: {Status.SCORED, Status.SKIPPED, Status.EXPIRED},
        Status.SCORED: {Status.DRAFTED, Status.REVIEWED, Status.SKIPPED, Status.EXPIRED},
        Status.DRAFTED: {Status.REVIEWED, Status.SKIPPED, Status.EXPIRED},
        Status.REVIEWED: {Status.APPLIED, Status.SCORED, Status.SKIPPED, Status.EXPIRED},
        Status.APPLIED: set(),
        Status.SKIPPED: {Status.NEW, Status.SCORED},
        Status.EXPIRED: set(),
    }

    job_id = models.CharField(max_length=96, unique=True)  # dedup key
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    skills = models.JSONField(default=list, blank=True)
    budget_type = models.CharField(max_length=8, choices=BudgetType.choices)
    budget_min = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    budget_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="USD")
    proposals_bucket = models.CharField(max_length=16, blank=True)  # "< 5", "5-10", "20+"
    client = models.ForeignKey(
        ClientProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs"
    )
    matched_filter = models.ForeignKey(
        SavedFilter, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs"
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    posted_at = models.DateTimeField(null=True, blank=True)
    # Outcomes past "applied" — set manually (admin / Telegram) for the funnel.
    interviewed_at = models.DateTimeField(null=True, blank=True)
    hired_at = models.DateTimeField(null=True, blank=True)
    review_notified_at = models.DateTimeField(null=True, blank=True)  # Telegram card sent
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-posted_at",)
        indexes = [
            models.Index(fields=("status",)),
            models.Index(fields=("-posted_at",)),
        ]

    def __str__(self):
        return self.title

    def transition_to(self, new_status, *, save=True):
        """Move to new_status if the transition is allowed, else raise ValueError."""
        current = self.Status(self.status)
        target = self.Status(new_status)
        if target not in self.ALLOWED_TRANSITIONS[current]:
            raise ValueError(f"Illegal transition {current} -> {target}")
        self.status = target
        if save:
            self.save(update_fields=["status", "updated_at"])
        return self
