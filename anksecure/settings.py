# settings.py — HTTPS / HSTS / proxy enforcement removed (copy-paste)
from pathlib import Path
import os
import warnings

BASE_DIR = Path(__file__).resolve().parent.parent

# --- SECURITY & ENV SETTINGS ---
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "change-me-in-prod")
DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() == "true"

# ALLOWED_HOSTS comes from env (comma separated). default keeps local hosts.
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,madpips.up.railway.app")
    .split(",")
    if h.strip()
]

# Optional explicit production host (helps if you still want to set cookie domain)
PROD_HOST = os.environ.get("DJANGO_PROD_HOST", "madpips.up.railway.app").strip()

# --- CSRF & Cookie Settings ---
# You may set DJANGO_CSRF_TRUSTED_ORIGINS as a comma-separated list (must include scheme if using Django 4+).
raw_csrf_origins = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").strip()

if raw_csrf_origins:
    # Operator controls exact values (must include scheme per Django 4+).
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in raw_csrf_origins.split(",") if o.strip()]
else:
    # Default safe dev values: http local addresses only (no automatic https insertion)
    if DEBUG:
        CSRF_TRUSTED_ORIGINS = [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ]
    else:
        # Production: leave empty by default (so you can set explicit env values)
        CSRF_TRUSTED_ORIGINS = []

# Cookie domain (optional) - set via env if needed
CSRF_COOKIE_DOMAIN = os.environ.get("DJANGO_CSRF_COOKIE_DOMAIN", PROD_HOST if not DEBUG else "")
if CSRF_COOKIE_DOMAIN == "":
    CSRF_COOKIE_DOMAIN = None

# Configure cookie security based on env or DEBUG
def parse_bool_env(name, default):
    v = os.environ.get(name, "").strip().lower()
    if v in ("true", "1"):
        return True
    if v in ("false", "0"):
        return False
    return default

CSRF_COOKIE_SECURE = parse_bool_env("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_SECURE = parse_bool_env("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)

# --- APPLICATIONS ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "axes",
    "csp",
]

# --- MIDDLEWARE ---
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise not required for dev; it's conditionally inserted below if available.
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
    "anksecure.security.middleware.SecurityIdleTimeoutMiddleware",
    "anksecure.security.middleware.TenantBindingMiddleware",
    "anksecure.security.middleware.AntiCrawlerHeaderMiddleware",
]

ROOT_URLCONF = "anksecure.urls"

# --- TEMPLATES ---
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "core" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "anksecure.wsgi.application"

# --- DATABASE ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# --- AUTHENTICATION ---
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# --- INTERNATIONALIZATION ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- STATIC FILES ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Try to include WhiteNoise middleware and storage only if the package is available.
WHITENOISE_AVAILABLE = False
try:
    import whitenoise  # noqa: F401

    WHITENOISE_AVAILABLE = True
except Exception:
    WHITENOISE_AVAILABLE = False

if WHITENOISE_AVAILABLE and not DEBUG:
    # insert WhiteNoise middleware after SecurityMiddleware
    if "whitenoise.middleware.WhiteNoiseMiddleware" not in MIDDLEWARE:
        MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
else:
    STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- AXES (Lockout) ---
AXES_FAILURE_LIMIT = int(os.environ.get("AXES_FAILURE_LIMIT", 5))
AXES_COOLOFF_TIME = float(os.environ.get("AXES_COOLOFF_TIME", 0.5))
AXES_LOCK_OUT_AT_FAILURE = os.environ.get("AXES_LOCK_OUT_AT_FAILURE", "True").lower() == "true"
AXES_LOCKOUT_TEMPLATE = os.environ.get("AXES_LOCKOUT_TEMPLATE", "security/lockout.html")
AXES_RESET_ON_SUCCESS = os.environ.get("AXES_RESET_ON_SUCCESS", "True").lower() == "true"

# --- IDLE TIMEOUT ---
SECURITY_IDLE_TIMEOUT_SECONDS = int(os.environ.get("SECURITY_IDLE_TIMEOUT_SECONDS", 1800))

# --- SECURITY HEADERS (minimal, no forced HTTPS) ---
SECURE_BROWSER_XSS_FILTER = os.environ.get("SECURE_BROWSER_XSS_FILTER", "True").lower() == "true"
SECURE_CONTENT_TYPE_NOSNIFF = os.environ.get("SECURE_CONTENT_TYPE_NOSNIFF", "True").lower() == "true"

# IMPORTANT: we intentionally do NOT set SECURE_SSL_REDIRECT, SECURE_HSTS_*, or SECURE_PROXY_SSL_HEADER here.
# This prevents Django from enforcing HTTPS / HSTS or relying on proxy headers.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# Remove proxy header usage:
SECURE_PROXY_SSL_HEADER = None

X_FRAME_OPTIONS = os.environ.get("X_FRAME_OPTIONS", "DENY")

# --- Extra helpful defaults & safety checks ---
if not DEBUG and SECRET_KEY == "change-me-in-prod":
    warnings.warn("DJANGO_SECRET_KEY is not set to a secure value in production!", RuntimeWarning)

if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

# --- END OF SETTINGS ---



# from pathlib import Path
# import os

# BASE_DIR = Path(__file__).resolve().parent.parent

# # --- SECURITY & ENV SETTINGS ---
# SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
# DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() == "true"
# ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
# # --- CSRF & Cookie Settings ---
# CSRF_TRUSTED_ORIGINS = [
#     "https://madpips.up.railway.app",
#     "madpips.up.railway.app",           # add bare hostname
#     "http://127.0.0.1:8000",
#     "127.0.0.1:8000",
#     "http://localhost:8000",
#     "localhost:8000",
# ]
# # --- APPLICATIONS ---
# INSTALLED_APPS = [
#     "django.contrib.admin",
#     "django.contrib.auth",
#     "django.contrib.contenttypes",
#     "django.contrib.sessions",
#     "django.contrib.messages",
#     "django.contrib.staticfiles",
#     "core",
#     "axes",
#     "csp",
# ]

# # --- MIDDLEWARE ---
# MIDDLEWARE = [
#     "django.middleware.security.SecurityMiddleware",
#     "whitenoise.middleware.WhiteNoiseMiddleware",
#     "django.contrib.sessions.middleware.SessionMiddleware",
#     "django.middleware.common.CommonMiddleware",
#     "django.middleware.csrf.CsrfViewMiddleware",
#     "django.contrib.auth.middleware.AuthenticationMiddleware",
#     "django.contrib.messages.middleware.MessageMiddleware",
#     "django.middleware.clickjacking.XFrameOptionsMiddleware",
#     "axes.middleware.AxesMiddleware",
#     "anksecure.security.middleware.SecurityIdleTimeoutMiddleware",
#     "anksecure.security.middleware.TenantBindingMiddleware",
#     "anksecure.security.middleware.AntiCrawlerHeaderMiddleware",
# ]

# ROOT_URLCONF = "anksecure.urls"

# # --- TEMPLATES ---
# TEMPLATES = [
#     {
#         "BACKEND": "django.template.backends.django.DjangoTemplates",
#         "DIRS": [BASE_DIR / "core" / "templates"],
#         "APP_DIRS": True,
#         "OPTIONS": {
#             "context_processors": [
#                 "django.template.context_processors.debug",
#                 "django.template.context_processors.request",
#                 "django.contrib.auth.context_processors.auth",
#                 "django.contrib.messages.context_processors.messages",
#             ],
#         },
#     },
# ]

# WSGI_APPLICATION = "anksecure.wsgi.application"

# # --- DATABASE ---
# DATABASES = {
#     "default": {
#         "ENGINE": "django.db.backends.sqlite3",
#         "NAME": BASE_DIR / "db.sqlite3",
#     }
# }

# # --- AUTHENTICATION ---
# AUTHENTICATION_BACKENDS = [
#     "axes.backends.AxesStandaloneBackend",
#     "django.contrib.auth.backends.ModelBackend",
# ]

# LOGIN_URL = "login"
# LOGIN_REDIRECT_URL = "dashboard"
# LOGOUT_REDIRECT_URL = "login"

# # --- INTERNATIONALIZATION ---
# LANGUAGE_CODE = "en-us"
# TIME_ZONE = "UTC"
# USE_I18N = True
# USE_TZ = True

# # --- STATIC FILES ---
# STATIC_URL = "static/"
# STATIC_ROOT = BASE_DIR / "staticfiles"
# STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# # --- AXES (Lockout) ---
# AXES_FAILURE_LIMIT = 5
# AXES_COOLOFF_TIME = 0.5
# AXES_LOCK_OUT_AT_FAILURE = True
# AXES_LOCKOUT_TEMPLATE = "security/lockout.html"
# AXES_RESET_ON_SUCCESS = True

# # --- IDLE TIMEOUT ---
# SECURITY_IDLE_TIMEOUT_SECONDS = 1800

# # # --- SECURITY HEADERS ---
# # SECURE_BROWSER_XSS_FILTER = True
# # SECURE_CONTENT_TYPE_NOSNIFF = True
# # SECURE_SSL_REDIRECT = not DEBUG
# # SESSION_COOKIE_SECURE = not DEBUG
# # CSRF_COOKIE_SECURE = not DEBUG
# # X_FRAME_OPTIONS = "DENY"
# # SECURE_HSTS_SECONDS = 31536000
# # # --- Railway HTTPS Fix (prevent redirect loops) ---
# # SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# # SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# # SECURE_HSTS_PRELOAD = True
# # --- SECURITY HEADERS ---
# SECURE_BROWSER_XSS_FILTER = True
# SECURE_CONTENT_TYPE_NOSNIFF = True
# SECURE_SSL_REDIRECT = False
# # SESSION_COOKIE_SECURE = not DEBUG
# # CSRF_COOKIE_SECURE = not DEBUG
# X_FRAME_OPTIONS = "DENY"
# SECURE_HSTS_SECONDS = 31536000
# # --- Railway HTTPS Fix (prevent redirect loops) ---
# SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_HSTS_PRELOAD = True
# CSRF_COOKIE_DOMAIN = "madpips.up.railway.app"
# CSRF_COOKIE_SECURE = True
# SESSION_COOKIE_SECURE = True








