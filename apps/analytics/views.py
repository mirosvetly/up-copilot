from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from django.conf import settings

from . import metrics
from .habit import habit
from .money import money


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
            "money": money(),
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


@require_POST
def money_add(request):
    """Add one ledger line from the analytics form. Bad input is ignored with a message."""
    from decimal import Decimal, InvalidOperation

    from django.contrib import messages

    from .models import MoneyEntry

    kind = request.POST.get("kind", "")
    try:
        usd = Decimal(request.POST.get("usd") or "0").quantize(Decimal("0.01"))
        connects = int(request.POST.get("connects") or 0)
        if kind not in MoneyEntry.Kind.values or usd < 0 or connects < 0:
            raise ValueError
    except (InvalidOperation, ValueError):
        messages.error(request, "Не получилось сохранить: проверь сумму и коннекты")
        return redirect("analytics:analytics")
    MoneyEntry.objects.create(
        kind=kind, usd=usd, connects=connects, note=request.POST.get("note", "")[:120],
        **({"date": request.POST["date"]} if request.POST.get("date") else {}),
    )
    return redirect("analytics:analytics")


@require_POST
def money_delete(request, pk):
    from .models import MoneyEntry

    MoneyEntry.objects.filter(pk=pk).delete()
    return redirect("analytics:analytics")
