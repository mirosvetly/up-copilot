# Upwork Copilot

Personal, single-user assistant that automates the Upwork job funnel up to but
never including the final submit. **Sending a proposal is always manual** (Upwork
has no proposal API and automated submission violates its ToS; a human stays in
the loop).

Pipeline: **collect, score, draft cover letter, answer screening, review, (you send)**.
Every stage is idempotent and status-gated, so it is safe to re-run.

## What it does

1. **Collect.** Pulls fresh Upwork jobs from a provider. Primary source is the
   Vibeworker REST API (an Upwork wrapper); fallback is Upwork alert emails over
   IMAP (Gmail). Upwork only (the source host must be `upwork.com`, matched by
   parsed host, not a substring), fresh only (nothing older than
   `MAX_JOB_AGE_HOURS`, default 24h), and de-duplicated against a `SeenJob`
   ledger that survives deletion, so cleared jobs are never re-imported or
   re-scored (no paying twice).
2. **Score.** Claude Haiku scores each job 0 to 100 against the editable prompt
   of the job's track: stack match, budget vs floor, competition (Upwork
   `connects` as a crowdedness proxy, since proposal counts are not exposed),
   client adequacy, and freshness. If the LLM call fails, it falls back to a
   transparent rule scorer. `DRAFT_MIN_SCORE` gates auto-drafting.
3. **Draft.** For jobs above the threshold, Claude Sonnet writes a cover letter
   in the voice of the track's persona. Anti-AI-tell rules: no filler in the
   opening line, no long dashes, no greeting up front, a dry self-aware P.S.,
   and aggressive timelines.
4. **Screen.** RAG answers to client screening questions from a `KnowledgeBase`
   (when a job carries them).
5. **Send.** Manual. The cover-letter card has a "copy and open on Upwork"
   button that copies the English original, opens the posting, and marks the
   card as sent (with an undo).

## Tracks (personas)

A track is an editable persona stored in the DB: skills, rate, portfolio,
scoring prompt, and letter instructions. Ships with three ("Разработка",
"Лендинги", "События"). A saved search (a set of keywords) points at a track, so
every job it collects is scored and drafted under that persona. Editable at
`/settings/tracks/`. `SavedFilter.track` is the routing link; a job with no
track falls back to the default.

## Translation (two independent layers)

- **Content** (job title/description, cover letters, scoring reasons) is
  translated to Russian for free with Google (deep-translator), cached in
  `*_ru` fields, and pulled in lazily in a background thread so the detail page
  opens instantly in English and the RU fills in when ready. A per-card RU/EN
  toggle switches all card content at once. The copy button always copies the
  English letter (that is what the client receives).
- **UI chrome** (buttons, statuses, headers) is localised with Django gettext
  i18n, with an RU/EN switcher in the sidebar. Russian is the source language;
  `locale/en` is the English translation. Add any language with one `.po` file.

## UI

Job feed sorted by score (best unsent first), track filter pills
(Все / Разработка / Лендинги / События), a **Отправленные** tab, a "Пропустить
все" action that clears the untouched backlog, a manual **Обновить** button, and
an **Авто** toggle that polls the API for new jobs while the tab is open and
shows a non-intrusive banner. Plus the **Аналитика** screen (funnel, keywords,
heatmap) and a Prometheus/JSON `/metrics` endpoint.

## Architecture

Django 5 with Celery + Redis for the background pipeline (or run it by hand),
PostgreSQL in production (behind PgBouncer, `CONN_MAX_AGE=0`,
`DISABLE_SERVER_SIDE_CURSORS=True`) and sqlite locally.

| App | Responsibility |
|-----|----------------|
| `core` | base model, shared LLM access (`core/llm.py`), free translation (`core/translate.py`) |
| `tracks` | `Track` persona model + `/settings/tracks/` editor |
| `jobs` | `JobPosting`/`ClientProfile`/`SavedFilter`/`SeenJob`, status machine, provider seam (mock/vibeworker/gmail), collector, feed + detail + sent + refresh views |
| `scoring` | `JobScore`, rule-based + LLM scorer, embeddings (mock/Voyage) + cosine similarity |
| `letters` | `CoverLetterDraft` (versioned), GitHub RAG (mock/real), generator, copy-and-send |
| `screening` | `KnowledgeBase`, `ScreeningQuestion/Answer`, RAG answers |
| `analytics` | funnel / keyword / heatmap metrics, `/metrics` |
| `review` | Telegram review bot (aiogram): card + Approve/Skip/Edit |

Status machine: `new, scored, drafted, reviewed, applied` (+ `skipped`,
`expired`), enforced by `JobPosting.transition_to()`. `drafted <-> applied` is the
one-click send and its undo.

Model split by cost: bulk scoring runs on cheap Haiku
(`ANTHROPIC_SCORER_MODEL`), cover letters and screening on the stronger Sonnet
(`ANTHROPIC_MODEL`).

## Mock-first design

Every external dependency has a **mock (default, no key) / real (env-gated)**
seam, so the whole app runs and is verifiable on sqlite with zero credentials.
Tests force every seam to mock, so the suite never touches the network.

| Switch | `mock` (default) | real |
|--------|------------------|------|
| `JOB_PROVIDER` | fixture jobs | `vibeworker` (REST, `VIBEWORKER_API_KEY`), `gmail` (IMAP alert emails), `upwork` (OAuth stub) |
| `LLM_PROVIDER` | deterministic templates | `anthropic` (Claude) |
| `JOB_SCORER` | `rule` | `llm` |
| `TRANSLATE_PROVIDER` | off | `google` (free, no key) |
| `EMBEDDING_PROVIDER` | hashed bag-of-words | `voyage` (voyage-3) |
| `GITHUB_PROVIDER` | repos from `stack_profile.yaml` | `github` API |
| Telegram | no-op without token | set `TELEGRAM_BOT_TOKEN` |

Other knobs: `MAX_JOB_AGE_HOURS` (freshness cutoff), `DRAFT_MIN_SCORE`
(auto-draft threshold), `ANTHROPIC_SCORER_MODEL` / `ANTHROPIC_MODEL` (model split).

## Run locally (sqlite, no keys)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py compilemessages -l en   # UI translations
python manage.py seed_demo               # KB + collect + score + draft + screen on mock data
python manage.py createsuperuser         # for /admin
python manage.py runserver 8012          # /  feed, /analytics, /settings/tracks/, /admin, /metrics
```

## Run the full stack (auto pipeline)

```bash
cp .env.example .env                      # fill in keys
docker compose up                         # web + db + pgbouncer + redis + worker + beat + bot
```

Celery beat runs the pipeline every minute. Without Celery, the **Обновить**
button and the **Авто** toggle poll the API on demand from the browser.

## Going live

- **Vibeworker** (primary): key from tryvibeworker.com/settings into
  `VIBEWORKER_API_KEY`, set `JOB_PROVIDER=vibeworker`. Free plan is 100 results
  per day (charged per returned result, duplicates included); premium removes
  the limit and enables webhooks.
- **Gmail** (fallback): enable Upwork job alerts on your saved searches, create
  a Google app password, set `GMAIL_IMAP_USER` + `GMAIL_IMAP_PASSWORD`,
  `JOB_PROVIDER=gmail`. Emails give truncated titles and no client hire rate.
- **Claude**: `ANTHROPIC_API_KEY`, `LLM_PROVIDER=anthropic`, `JOB_SCORER=llm`.
  Scoring uses Haiku, letters use Sonnet.
- **Tracks**: edit personas, prompts, skills, rate, and keywords at
  `/settings/tracks/`. Tracks live in the DB, not in git; a seed migration for
  default tracks is an easy follow-up.

## Tests

```bash
python manage.py test
```

106 tests, hermetic (no network, no paid API calls).
