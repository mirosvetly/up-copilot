from __future__ import annotations

import json

from django import forms
from django.utils.translation import gettext, gettext_lazy as _

from .models import Track


class _LinesField(forms.CharField):
    """A textarea whose lines become a JSON list of strings (and back)."""

    widget = forms.Textarea(attrs={"rows": 5})

    def prepare_value(self, value):
        return "\n".join(value) if isinstance(value, list) else (value or "")

    def clean(self, value):
        value = super().clean(value)
        return [ln.strip() for ln in value.splitlines() if ln.strip()]


class _ProjectsField(forms.CharField):
    """Portfolio as JSON: [{"repo": "name", "skills": ["A", "B"]}, …]."""

    widget = forms.Textarea(attrs={"rows": 6})

    def prepare_value(self, value):
        if isinstance(value, list):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return value or "[]"

    def clean(self, value):
        value = super().clean(value).strip() or "[]"
        try:
            data = json.loads(value)
        except json.JSONDecodeError as e:
            raise forms.ValidationError(gettext("Невалидный JSON: %(err)s") % {"err": e})
        ok = isinstance(data, list) and all(
            isinstance(p, dict) and p.get("repo") and isinstance(p.get("skills", []), list)
            for p in data
        )
        if not ok:
            raise forms.ValidationError(gettext(
                'Ожидается список объектов вида {"repo": "...", "skills": ["...", ...]} '
                "(skills — список строк)."
            ))
        return data


class TrackForm(forms.ModelForm):
    skills = _LinesField(required=False, help_text=_("По одному навыку в строке."))
    red_flag_phrases = _LinesField(required=False, help_text=_("По одной фразе в строке."))
    projects = _ProjectsField(required=False)

    class Meta:
        model = Track
        fields = [
            "name", "is_default", "scorer_role", "job_analysis_prompt",
            "cover_letter_instructions", "screening_instructions", "signoff",
            "skills", "min_hourly_rate", "projects", "red_flag_phrases",
        ]
        widgets = {
            "job_analysis_prompt": forms.Textarea(attrs={"rows": 5}),
            "cover_letter_instructions": forms.Textarea(attrs={"rows": 4}),
            "screening_instructions": forms.Textarea(attrs={"rows": 3}),
            "signoff": forms.Textarea(attrs={"rows": 2}),
        }

