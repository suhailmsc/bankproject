"""
Northstar Bank - Django settings.

Twelve-factor style: every environment-specific value comes from an environment
variable (see .env.example). Defaults are safe for production; developer
conveniences are only switched on when DEBUG=1.

LEARNING PROJECT: fictional bank, fictional money. Not for real customers.
"""
import os
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from dotenv import load_dotenv

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
# Load environment variables from the project-root .env before reading settings.
load_dotenv(BASE_DIR / ".env")

TESTING = "test" in sys.argv


# --------------------------------------------------------------------------- #
# Env helpers
# --------------------------------------------------------------------------- #
def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def env_int(name, default):
    return int(os.environ.get(name, default))


def env_decimal(name, default):
    return Decimal(os.environ.get(name, default))


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.environ.get("SECRET_KEY", "")
_WEAK_KEY_MARKERS = ("change-me", "changeme", "insecure", "local-development", "secret")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "dev-only-insecure-key-not-for-production-use-0123456789"
    else:
        raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG is off.")
elif not (DEBUG or TESTING) and (
    len(SECRET_KEY) < 40 or any(marker in SECRET_KEY.lower() for marker in _WEAK_KEY_MARKERS)
):
    raise ImproperlyConfigured(
        "SECRET_KEY is too short or looks like a placeholder. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "*")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Customer portal and staff console live on different URL prefixes. The staff
# console prefix is deliberately NOT /admin/ and is configurable.
ADMIN_URL = "admin/"

INSTALLED_APPS = [
    "core.apps.StaffAdminConfig",  # replaces django.contrib.admin (custom AdminSite)
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "axes",
    "accounts",
    "banking",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "core.middleware.HealthCheckMiddleware",  # before host validation: ALB/ECS probes
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.AdminIsolationMiddleware",  # customers never see the staff console
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "banking_project.urls"
WSGI_APPLICATION = "banking_project.wsgi.application"

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
                "core.context_processors.bank",
            ],
        },
    },
]

# --------------------------------------------------------------------------- #
# Database  (PostgreSQL in Docker/AWS, SQLite fallback for quick local runs)
# --------------------------------------------------------------------------- #
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=env_int("DB_CONN_MAX_AGE", 60),
        conn_health_checks=True,
    )
}
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    # IMMEDIATE takes the write lock up-front so concurrent transfers queue
    # instead of failing half-way (SQLite has no row locks).
    DATABASES["default"].setdefault("OPTIONS", {})["transaction_mode"] = "IMMEDIATE"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # must be first: brute-force lockout
    "accounts.backends.EmailBackend",
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",  # verifies/upgrades old hashes
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "accounts.validators.ComplexityValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "banking:dashboard"
LOGOUT_REDIRECT_URL = "home"
PASSWORD_RESET_TIMEOUT = 60 * 30  # reset links live 30 minutes

# Brute-force protection (django-axes)
AXES_FAILURE_LIMIT = env_int("AXES_FAILURE_LIMIT", 5)
AXES_COOLOFF_TIME = timedelta(minutes=env_int("AXES_COOLOFF_MINUTES", 15))
AXES_LOCKOUT_PARAMETERS = [["ip_address", "username"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/lockout.html"
AXES_ENABLED = not TESTING

# Sessions: short idle timeout, like a real banking portal.
SESSION_IDLE_SECONDS = env_int("SESSION_IDLE_SECONDS", 15 * 60)
SESSION_COOKIE_AGE = SESSION_IDLE_SECONDS
SESSION_SAVE_EVERY_REQUEST = True  # sliding window => idle timeout
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_NAME = "nsb_session"
CSRF_COOKIE_NAME = "nsb_csrf"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"

# --------------------------------------------------------------------------- #
# Transport security (HTTPS everywhere outside local dev)
# --------------------------------------------------------------------------- 
HTTPS_ONLY = env_bool("HTTPS_ONLY", not DEBUG)
BEHIND_PROXY = env_bool("BEHIND_PROXY", False)  # True behind ALB / nginx / CloudFront
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", 1 if BEHIND_PROXY else 0)

if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = False
    AXES_IPWARE_PROXY_COUNT = TRUSTED_PROXY_COUNT
    AXES_IPWARE_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]

SECURE_SSL_REDIRECT = HTTPS_ONLY
SESSION_COOKIE_SECURE = HTTPS_ONLY
CSRF_COOKIE_SECURE = HTTPS_ONLY
SECURE_HSTS_SECONDS = env_int("HSTS_SECONDS", 31536000) if HTTPS_ONLY else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = HTTPS_ONLY
SECURE_HSTS_PRELOAD = False  # opt in deliberately once the domain is final
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024  # no uploads in this app; keep bodies small
FILE_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024

# --------------------------------------------------------------------------- #
# Static files (WhiteNoise)
# --------------------------------------------------------------------------- #
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if (DEBUG or TESTING)
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# --------------------------------------------------------------------------- #
# Cache (Redis when REDIS_URL is set; per-process memory otherwise)
# --------------------------------------------------------------------------- #
if os.environ.get("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.environ["REDIS_URL"],
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Northstar Bank <no-reply@northstar.example>")
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")

# --------------------------------------------------------------------------- #
# Internationalisation
# --------------------------------------------------------------------------- #
LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------- #
# Bank business rules  (all overridable by env)
# --------------------------------------------------------------------------- #
BANK_NAME = "Northstar Bank"
BANK_BRANCH_CODE = "NSTB0000001"  # fictional IFSC-style branch code
BANK_CURRENCY = "INR"
DEMO_MODE = env_bool("DEMO_MODE", True)  # lets customers add *fictional* funds
DEMO_MAX_FUNDING = env_decimal("DEMO_MAX_FUNDING", "50000")
MAX_ACCOUNTS_PER_CUSTOMER = env_int("MAX_ACCOUNTS_PER_CUSTOMER", 5)
TRANSFER_MIN = env_decimal("TRANSFER_MIN", "1")
TRANSFER_MAX_PER_TXN = env_decimal("TRANSFER_MAX_PER_TXN", "100000")
DAILY_LIMIT_KYC_VERIFIED = env_decimal("DAILY_LIMIT_KYC_VERIFIED", "200000")
DAILY_LIMIT_KYC_PENDING = env_decimal("DAILY_LIMIT_KYC_PENDING", "25000")
BENEFICIARY_COOLING_MINUTES = env_int("BENEFICIARY_COOLING_MINUTES", 0)
TRANSFER_REVIEW_TTL_SECONDS = env_int("TRANSFER_REVIEW_TTL_SECONDS", 300)
REQUIRE_EMAIL_VERIFICATION = env_bool("REQUIRE_EMAIL_VERIFICATION", not DEBUG)
MIN_CUSTOMER_AGE = 18

# --------------------------------------------------------------------------- #
# Logging (stdout -> CloudWatch / docker logs)
# --------------------------------------------------------------------------- #
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "banking.audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
