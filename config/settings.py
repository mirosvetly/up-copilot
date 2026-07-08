from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, "dev-insecure-change-me"),
    ALLOWED_HOSTS=(list, ["*"]),
    # Provider swaps: "mock" (no key, deterministic) vs real API. Default mock
    # everywhere so the whole app runs on sqlite with zero external credentials.
    JOB_PROVIDER=(str, "mock"),  # mock | upwork | vibeworker | gmail
    LLM_PROVIDER=(str, "mock"),  # mock | anthropic
    GITHUB_PROVIDER=(str, "mock"),  # mock | github
    EMBEDDING_PROVIDER=(str, "mock"),  # mock | voyage
    JOB_SCORER=(str, "rule"),  # rule | llm
    DRAFT_MIN_SCORE=(int, 50),  # only auto-draft cover letters at/above this score
    VIBEWORKER_API_KEY=(str, ""),  # tryvibeworker.com/settings -> Developer
    GMAIL_IMAP_USER=(str, ""),  # JOB_PROVIDER=gmail: mailbox receiving Upwork job alerts
    GMAIL_IMAP_PASSWORD=(str, ""),  # Google app password (myaccount.google.com/apppasswords)
    ANTHROPIC_API_KEY=(str, ""),
    ANTHROPIC_MODEL=(str, "claude-sonnet-5"),
    VOYAGE_API_KEY=(str, ""),
    GITHUB_TOKEN=(str, ""),
    GITHUB_USER=(str, ""),
    TELEGRAM_BOT_TOKEN=(str, ""),
    TELEGRAM_CHAT_ID=(str, ""),
    SITE_URL=(str, "http://localhost:8012"),
    TIME_ZONE=(str, "Europe/Moscow"),
    CELERY_BROKER_URL=(str, "redis://localhost:6379/0"),
    CELERY_RESULT_BACKEND=(str, "redis://localhost:6379/1"),
    # Default sqlite so `manage.py check`/tests run with no Postgres/Docker.
    DATABASE_URL=(str, f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.tracks",
    "apps.jobs",
    "apps.scoring",
    "apps.letters",
    "apps.screening",
    "apps.analytics",
    "apps.review",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.freelancer",
            ],
        },
    },
]

DATABASES = {"default": env.db()}
# Reference-project pattern: PgBouncer transaction pooling. Each request opens a
# fresh connection (CONN_MAX_AGE=0) and server-side cursors are unusable through
# a transaction-pooled bouncer, so disable them.
DATABASES["default"]["CONN_MAX_AGE"] = 0
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Celery ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

# --- App config: provider swaps ---
JOB_PROVIDER = env("JOB_PROVIDER")
LLM_PROVIDER = env("LLM_PROVIDER")
GITHUB_PROVIDER = env("GITHUB_PROVIDER")
EMBEDDING_PROVIDER = env("EMBEDDING_PROVIDER")
JOB_SCORER = env("JOB_SCORER")
VIBEWORKER_API_KEY = env("VIBEWORKER_API_KEY")
GMAIL_IMAP_USER = env("GMAIL_IMAP_USER")
GMAIL_IMAP_PASSWORD = env("GMAIL_IMAP_PASSWORD")
DRAFT_MIN_SCORE = env("DRAFT_MIN_SCORE")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL")
VOYAGE_API_KEY = env("VOYAGE_API_KEY")
GITHUB_TOKEN = env("GITHUB_TOKEN")
GITHUB_USER = env("GITHUB_USER")
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
SITE_URL = env("SITE_URL")
