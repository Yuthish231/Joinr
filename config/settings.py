"""Joinr settings. Everything environment-specific comes from env vars."""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env("DEBUG")
SECRET_KEY = env("SECRET_KEY", default="dev-only-secret-change-me")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "access",
    "lifecycle",
    "directory",
    "audit",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "accounts.middleware.SessionGuardMiddleware",
    "accounts.middleware.PasswordChangeRequiredMiddleware",
    "accounts.middleware.NoStoreMiddleware",
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
                "core.context_processors.app",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "directory.backends.LDAPBackend",  # tried first when LDAP_ENABLED
    "accounts.backends.LockoutModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", default="Asia/Kolkata")
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --------------------------------------------------------------------------
# Session management
# --------------------------------------------------------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = env.int("SESSION_IDLE_SECONDS", default=30 * 60)  # idle timeout
SESSION_SAVE_EVERY_REQUEST = True  # makes the cookie age an inactivity window
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env.bool("COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_HTTPONLY = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
ABSOLUTE_SESSION_SECONDS = env.int("SESSION_ABSOLUTE_SECONDS", default=8 * 60 * 60)
MAX_CONCURRENT_SESSIONS = env.int("MAX_CONCURRENT_SESSIONS", default=3)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Brute-force lockout
LOCKOUT_THRESHOLD = env.int("LOCKOUT_THRESHOLD", default=5)
LOCKOUT_MINUTES = env.int("LOCKOUT_MINUTES", default=15)

# Lifecycle
TEMP_PASSWORD_LENGTH = 14
# Access of a leaver ends at this local hour on their last working day (or any time after that day).
LEAVER_CUTOFF_HOUR = env.int("LEAVER_CUTOFF_HOUR", default=18)

# --------------------------------------------------------------------------
# LDAP (see directory/). Off by default; docker-compose enables it.
# --------------------------------------------------------------------------
LDAP_ENABLED = env.bool("LDAP_ENABLED", default=False)
LDAP_SERVER_URI = env("LDAP_SERVER_URI", default="ldap://localhost:389")
LDAP_BIND_DN = env("LDAP_BIND_DN", default="cn=admin,dc=joinr,dc=local")
LDAP_BIND_PASSWORD = env("LDAP_BIND_PASSWORD", default="")
LDAP_BASE_DN = env("LDAP_BASE_DN", default="dc=joinr,dc=local")
LDAP_USER_OU = env("LDAP_USER_OU", default="ou=People")
LDAP_GROUP_OU = env("LDAP_GROUP_OU", default="ou=Groups")
LDAP_DISABLED_OU = env("LDAP_DISABLED_OU", default="ou=Disabled")
LDAP_WRITE_BACK = env.bool("LDAP_WRITE_BACK", default=True)  # provision/disable in LDAP
LDAP_TIMEOUT = env.int("LDAP_TIMEOUT", default=5)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
