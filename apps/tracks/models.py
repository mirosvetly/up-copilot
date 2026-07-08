from django.db import models

from apps.core.models import TimeStampedModel


class Track(TimeStampedModel):
    """An editable freelancer persona. One per kind of work (dev, landing pages…).

    Holds everything the scorer / cover-letter / screening layers need: the
    persona, the prompts, and the stack (skills, rate, portfolio). A SavedFilter
    points at a Track, so every job it collects is scored and drafted in that
    persona's voice.
    """

    name = models.CharField(max_length=80, unique=True)
    is_default = models.BooleanField(
        default=False, help_text="Used for jobs whose saved search has no track."
    )

    # --- persona / prompts ---
    scorer_role = models.CharField(
        max_length=200, default="freelance developer",
        help_text="Who you are, one line — steers the scoring prompt.",
    )
    job_analysis_prompt = models.TextField(
        blank=True, help_text="How to judge a job's fit (fed to the LLM scorer)."
    )
    cover_letter_instructions = models.TextField(
        blank=True, help_text="How to write the cover letter."
    )
    screening_instructions = models.TextField(
        blank=True, help_text="How to answer client screening questions."
    )
    signoff = models.CharField(max_length=120, default="Best,\nFreelancer")

    # --- stack ---
    skills = models.JSONField(default=list, blank=True)  # ["Django", "React", …]
    min_hourly_rate = models.PositiveSmallIntegerField(default=0)  # USD/hr floor
    projects = models.JSONField(default=list, blank=True)  # [{"repo": str, "skills": [str]}]
    red_flag_phrases = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("-is_default", "name")

    def __str__(self):
        return self.name + (" (default)" if self.is_default else "")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Exactly one default across every write path (admin, form, shell):
        # get_default() must never face a tie it would break by name ordering.
        if self.is_default:
            Track.objects.exclude(pk=self.pk).update(is_default=False)

    @classmethod
    def get_default(cls) -> "Track | None":
        """The fallback track for jobs with no track of their own."""
        return cls.objects.filter(is_default=True).first() or cls.objects.first()
