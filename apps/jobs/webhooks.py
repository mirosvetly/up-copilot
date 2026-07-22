"""Push endpoint for Vibeworker job events — optional, secondary to polling.

Polling (VibeworkerProvider.fetch_jobs) is the right integration for the
normal case: up-copilot running on someone's own machine, behind a NAT/
firewall with no public URL. This webhook only helps the minority who've
deployed up-copilot on a public host and want push instead of polling —
it is not a replacement for polling and should not be presented as the
default integration path.

Vibeworker owns the filter/search definitions on its side; each webhook event
is one job, already tagged with the id of the Vibeworker-side filter that
matched it. We map that id back to a local SavedFilter (via
SavedFilter.vibeworker_filter_id) purely for track/persona assignment — the
matching itself already happened upstream.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import SavedFilter
from .providers.vibeworker import _is_excluded, _is_upwork, _too_crowded, raw_job_from_row
from .tasks import ingest_pushed_job

log = logging.getLogger(__name__)


def _client_ip(request: HttpRequest) -> str:
    return request.META.get("REMOTE_ADDR", "")


def _ip_allowed(request: HttpRequest) -> bool:
    # Empty allowlist (the default) accepts from anywhere — no auth yet, this
    # is a single-user deployment. Set VIBEWORKER_WEBHOOK_ALLOWED_IPS to lock
    # it down once Vibeworker's outbound IPs are known/stable.
    allowed = settings.VIBEWORKER_WEBHOOK_ALLOWED_IPS
    return not allowed or _client_ip(request) in allowed


@csrf_exempt
@require_POST
def vibeworker_webhook(request: HttpRequest) -> HttpResponse:
    if not _ip_allowed(request):
        log.warning("Vibeworker webhook: rejected request from %s", _client_ip(request))
        return JsonResponse({"error": "forbidden"}, status=403)

    try:
        row = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid json"}, status=400)

    if not isinstance(row, dict) or not row.get("title") or not (row.get("id") or row.get("upworkUrl")):
        return JsonResponse({"error": "missing job fields"}, status=400)

    # Same local guards the poller applies at collect time — these are this
    # install's own preferences (COLLECT_MAX_CONNECTS, EXCLUDE_KEYWORDS), not
    # something Vibeworker's filter config knows about.
    url = row.get("upworkUrl") or row.get("url") or ""
    if not _is_upwork(url):
        return JsonResponse({"status": "ignored", "reason": "not upwork"})
    if _too_crowded(row) or _is_excluded(row):
        return JsonResponse({"status": "ignored", "reason": "filtered"})

    filter_id = str(row.get("filterId") or "")
    matched_filter = None
    if filter_id:
        matched_filter = SavedFilter.objects.filter(vibeworker_filter_id=filter_id).first()
        if matched_filter is None:
            log.warning("Vibeworker webhook: no local SavedFilter for filterId=%s", filter_id)

    rj = raw_job_from_row(row)
    if matched_filter and matched_filter.require_verified_payment and not rj.client.verified_payment:
        return JsonResponse({"status": "ignored", "reason": "unverified payment"})

    result = ingest_pushed_job(rj, matched_filter=matched_filter)
    return JsonResponse({"status": result})
