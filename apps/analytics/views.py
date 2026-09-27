from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from django.conf import settings

from . import metrics
from .habit import habit


def analytics(request):
    return render(
        request,
        "analytics/analytics.html",
        {
            "stats": metrics.stat_cards(),
            "funnel": metrics.funnel(),
            "keywords": metrics.keywords(),
            "heat": metrics.heatmap(),
            "habit": habit(),
            "TIME_ZONE_NAME": settings.TIME_ZONE,
            "is_analytics": True,
        },
    )


def metrics_endpoint(request):
    """Prometheus text by default; ?format=json for a Grafana JSON datasource."""
    if request.GET.get("format") == "json":
        return JsonResponse({
            "funnel": dict(metrics.funnel_counts()),
            "keywords": metrics.keywords(),
        })
    return HttpResponse(metrics.prometheus_text(), content_type="text/plain; version=0.0.4")
