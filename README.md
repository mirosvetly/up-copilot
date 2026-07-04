# Upwork Copilot

Personal, single-user assistant that automates everything up to — but never
including — submitting an Upwork proposal. **The final "send" is always manual**
(automated submission violates Upwork ToS; human-in-the-loop is required).

Pipeline: **collect → score → draft cover letter → answer screening → review → (you send)**.

## Architecture

Django + Celery + Postgres/Redis, deployed via Docker Compose (PgBouncer
transaction pooling; `CONN_MAX_AGE=0`, `DISABLE_SERVER_SIDE_CURSORS=True`).

| App | Responsibility |
|-----|----------------|
| `core` | base model, shared LLM access (`core/llm.py`) |
| `jobs` | `JobPosting`/`ClientProfile`/`SavedFilter`, status machine, provider seam (mock/Upwork), collector, **Лента** + **Detail** screens |
| `scoring` | `JobScore`, rule-based + LLM scorer, embeddings (mock/Voyage) + cosine similarity, hand-edited `stack_profile.yaml` |
| `letters` | `CoverLetterDraft` (versioned), GitHub RAG (mock/real), generator, source-highlighted cover letters |
| `screening` | `KnowledgeBase`, `ScreeningQuestion/Answer`, RAG answer generation |
| `analytics` | funnel / keyword / heatmap metrics, **Аналитика** screen, `/metrics` (Prometheus + JSON for Grafana) |
| `review` | Telegram review bot (aiogram): card + Approve/Skip/Edit |

Status machine: `new → scored → drafted → reviewed → applied` (+ `skipped` / `expired`),
enforced by `JobPosting.transition_to()`.

## Mock-first design

Every external dependency has a **mock (default, no key) / real (env-gated)** seam,
so the whole app runs and is verifiable on sqlite with zero credentials:

| Switch | `mock` (default) | real |
|--------|------------------|------|
| `JOB_PROVIDER` | fixture jobs | `upwork` (blocked on OAuth approval — stub) |
| `LLM_PROVIDER` | deterministic templates | `anthropic` (Claude) |
| `EMBEDDING_PROVIDER` | hashed bag-of-words | `voyage` (voyage-3) |
| `GITHUB_PROVIDER` | repos from `stack_profile.yaml` | `github` API |
| `JOB_SCORER` | `rule` | `llm` |
| Telegram | no-op without token | set `TELEGRAM_BOT_TOKEN` |

Embeddings are stored in a JSON column with Python cosine — fine at single-user
scale; pgvector/ANN is an optional future upgrade.

## Run locally (sqlite, no keys)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo        # KB + collect + score + draft + screen on mock data
python manage.py createsuperuser  # for /admin
python manage.py runserver 8012   # /  Лента · /analytics · /admin · /metrics
```

## Run the full stack

```bash
cp .env.example .env
docker compose up            # web + db + pgbouncer + redis + worker + beat + bot
```

The Celery beat schedule runs the pipeline every minute (each stage is
status-gated and idempotent). The Telegram bot (`manage.py run_bot`) is a no-op
until `TELEGRAM_BOT_TOKEN` is set.

## Going live later

- **Upwork**: implement `apps/jobs/providers/upwork.py` when OAuth is approved, set `JOB_PROVIDER=upwork`.
- **LLM/embeddings/GitHub/Telegram**: set the corresponding `*_PROVIDER` + key in `.env`.
- Edit `stack_profile.yaml` (skills, min rate, projects) and the `KnowledgeBase` (admin) to tune scoring and screening answers.

## Tests

```bash
python manage.py test
```
