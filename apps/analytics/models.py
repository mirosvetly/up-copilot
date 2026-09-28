from django.db import models
from django.utils import timezone


class MoneyEntry(models.Model):
    """One line of the Upwork money ledger: a connects purchase, a subscription,
    another cost, or income actually received (after Upwork's fee)."""

    class Kind(models.TextChoices):
        CONNECTS = "connects", "Покупка коннектов"
        SPENT = "spent", "Коннекты на отклик"  # a proposal not in the tracker (e.g. deleted)
        SUBSCRIPTION = "subscription", "Подписка"
        OTHER = "other", "Другой расход"
        INCOME = "income", "Доход"

    date = models.DateField(default=timezone.localdate)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.CONNECTS)
    usd = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    connects = models.PositiveIntegerField(default=0)  # added (kind=connects) or used (kind=spent)
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ("-date", "-id")

    def __str__(self):
        return f"{self.date} {self.get_kind_display()} ${self.usd}"
