from django.contrib import admin

from .models import KnowledgeBase, ScreeningAnswer, ScreeningQuestion


@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ("category", "content")
    list_filter = ("category",)
    search_fields = ("content", "category")


@admin.register(ScreeningQuestion)
class ScreeningQuestionAdmin(admin.ModelAdmin):
    list_display = ("job", "order", "text")
    search_fields = ("text", "job__job_id")


@admin.register(ScreeningAnswer)
class ScreeningAnswerAdmin(admin.ModelAdmin):
    list_display = ("question", "model_name", "updated_at")
    search_fields = ("body",)
