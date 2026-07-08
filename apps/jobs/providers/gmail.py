from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from email.header import decode_header
from email.utils import parsedate_to_datetime

from django.conf import settings
from django.utils import timezone

from apps.jobs.models import SavedFilter

from .base import JobProvider, RawClient, RawJob, matches_filter

log = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
ALERT_SENDER = "donotreply@upwork.com"
LOOKBACK_DAYS = 3  # dedup by job_id makes re-reading the window idempotent
# imaplib SINCE needs English month names; strftime %b is locale-dependent.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_JOB_URL = re.compile(r"upwork\.com/jobs/~(\w+)")
_BUDGET = re.compile(r"^\s*(Hourly|Fixed): \$([\d,]+(?:\.\d+)?)(?: - \$([\d,]+(?:\.\d+)?))?", re.M)
_CLIENT_LINE = re.compile(r"^(.*\$[\d,.]+[KM]? spent.*)$", re.M)
_STARS = re.compile(r"([\d.]+) stars")
_SPENT = re.compile(r"\$([\d,.]+)([KM]?) spent")
_SKILLS_BLOCK = re.compile(r"^Skills:\n(.*?)\n\s*\n", re.M | re.S)


def _money(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def parse_alert(text: str, subject: str, posted_at: datetime | None) -> RawJob | None:
    """One Upwork 'New job alert' plain-text email -> RawJob, or None if not an alert."""
    text = text.replace("\r\n", "\n")  # IMAP bodies come with CRLF
    m_url = _JOB_URL.search(text)
    # The title line precedes the budget line and may itself start with
    # "Fixed: $..." — anchor the budget search past the title's job URL.
    m_budget = _BUDGET.search(text, m_url.end()) if m_url else None
    if not (m_url and m_budget):
        return None
    job_id = m_url.group(1)
    url = f"https://www.upwork.com/jobs/~{job_id}"

    # Subject carries the longest version of the (still truncated) title.
    title = subject.partition("New job alert:")[2].strip() or text.split(": http")[0].splitlines()[-1]
    title = title.rstrip(".…").strip()

    kind, lo, hi = m_budget.group(1).lower(), _money(m_budget.group(2)), m_budget.group(3)
    budget_min = None if (kind == "hourly" and lo == 0) else lo
    budget_max = _money(hi) if hi and _money(hi) > 0 else None

    # Parse the footer bottom-up: the description freely contains "$X spent"
    # or its own "Skills:" heading, so the real client line is the LAST
    # "$X spent" line before "View job details", and the real skills block
    # is the LAST one before the client line.
    vjd = text.find("\nView job details")
    tail_end = vjd if vjd != -1 else len(text)
    client_ms = list(_CLIENT_LINE.finditer(text, m_budget.end(), tail_end))
    m_client = client_ms[-1] if client_ms else None
    skills_ms = list(_SKILLS_BLOCK.finditer(text, m_budget.end(), m_client.start() if m_client else tail_end))
    m_skills = skills_ms[-1] if skills_ms else None

    # Description: between the budget LINE (not just the matched amounts —
    # "· Est. time …" rides on the same line) and the skills/client block,
    # with the "... more: <link>" tail and tracking URLs stripped.
    start = text.find("\n", m_budget.end())
    start = m_budget.end() if start == -1 else start
    end = m_skills.start() if m_skills else (m_client.start() if m_client else tail_end)
    desc = re.sub(r"\.{3} more: https?://\S+", "…", text[start:end])
    desc = re.sub(r"https?://\S+", "", desc).strip()

    skills = [ln.split(": http")[0].strip() for ln in m_skills.group(1).splitlines()] if m_skills else []

    verified, rating, spent, country = False, None, None, ""
    if m_client:
        line = m_client.group(1)
        verified = "Payment verified" in line
        if m := _STARS.search(line):
            # ClientProfile.avg_rating is numeric(2,1); emails say e.g. "4.95 stars"
            rating = Decimal(m.group(1)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if m := _SPENT.search(line):
            spent = _money(m.group(1)) * {"": 1, "K": 1000, "M": 1_000_000}[m.group(2)]
        country = line.rsplit("·", 1)[-1].strip()

    client = RawClient(
        upwork_client_id=f"gm:{job_id}",  # ponytail: alerts carry no client id — one profile per job
        verified_payment=verified,
        total_spent=spent,
        country=country,
        avg_rating=rating,
        raw={"line": m_client.group(1) if m_client else ""},
    )
    return RawJob(
        job_id=job_id,
        title=title,
        description=desc,
        skills=skills,
        budget_type=kind,
        budget_min=budget_min,
        budget_max=budget_max,
        currency="USD",
        proposals_bucket="",  # not present in alert emails
        posted_at=posted_at,
        client=client,
        raw={"url": url, "subject": subject, "source": "gmail-alert", "text": text},
    )


def _plain_text(msg: email.message.Message) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
    return ""


def _subject(msg: email.message.Message) -> str:
    return "".join(
        p.decode(c or "utf-8", "replace") if isinstance(p, bytes) else p
        for p, c in decode_header(msg["Subject"] or "")
    )


class GmailProvider(JobProvider):
    """Upwork 'New job alert' emails read over IMAP (Gmail app password).

    Fresh and free (straight from Upwork's saved-search alerts), but emails
    carry truncated titles/descriptions and no client hire-rate. Env:
    GMAIL_IMAP_USER + GMAIL_IMAP_PASSWORD (myaccount.google.com/apppasswords).
    Reads the last LOOKBACK_DAYS readonly; job_id dedup downstream absorbs
    re-reads, so no mailbox state is kept.
    """

    def fetch_jobs(self, saved_filter: SavedFilter) -> list[RawJob]:
        user = settings.GMAIL_IMAP_USER
        password = settings.GMAIL_IMAP_PASSWORD.replace(" ", "")
        if not (user and password):
            raise RuntimeError("GMAIL_IMAP_USER / GMAIL_IMAP_PASSWORD are not set")
        d = timezone.now() - timedelta(days=LOOKBACK_DAYS)
        since = f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"
        jobs: dict[str, RawJob] = {}
        conn = imaplib.IMAP4_SSL(IMAP_HOST, timeout=30)  # a stalled socket must not hang the beat task
        try:
            conn.login(user, password)
            conn.select("INBOX", readonly=True)
            _, data = conn.search(
                None, "FROM", f'"{ALERT_SENDER}"', "SINCE", since, "SUBJECT", '"New job alert"'
            )
            for msg_id in data[0].split():
                try:
                    _, d_ = conn.fetch(msg_id, "(BODY.PEEK[])")
                    msg = email.message_from_bytes(d_[0][1])
                except (TypeError, IndexError):
                    # message expunged between SEARCH and FETCH — skip it
                    log.warning("Skipping unfetchable message %s", msg_id)
                    continue
                posted = parsedate_to_datetime(msg["Date"]) if msg["Date"] else timezone.now()
                job = parse_alert(_plain_text(msg), _subject(msg), posted)
                if job and matches_filter(job, saved_filter):
                    jobs.setdefault(job.job_id, job)
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        return list(jobs.values())
