"""
Production settings (Render). Everything here differs from local on purpose;
docs/deployment.md explains each block and the error you get without it.
"""
from .base import *  # noqa: F401,F403
from django.core.exceptions import ImproperlyConfigured

from .base import MIDDLEWARE, SECRET_KEY, env

DEBUG = False

# Fail at startup, not on the first request: an empty or short key (e.g. a
# variable created in the dashboard but never filled in) would otherwise boot.
# 40, not Django's 50: Render's generateValue is 256 random bits written as
# 44 base64 characters, which is strong but trips Django's length heuristic
# (security.W009, silenced below for that reason).
if len(SECRET_KEY) < 40:
    raise ImproperlyConfigured('SECRET_KEY must be set to a long random value in production.')

# ── Hosts ────────────────────────────────────────────────────────────────
# Render sets RENDER_EXTERNAL_HOSTNAME (e.g. skills-web.onrender.com) on every
# service, so the default host works with no configuration; ALLOWED_HOSTS adds
# custom domains. Without the right host every request is a 400 Bad Request.
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])
if RENDER_HOST := env('RENDER_EXTERNAL_HOSTNAME', default=''):
    ALLOWED_HOSTS.append(RENDER_HOST)
# Django 4+ checks the Origin of every POST against this list: without it,
# login and upload fail with "403 CSRF verification failed".
CSRF_TRUSTED_ORIGINS = [f'https://{h}' for h in ALLOWED_HOSTS if h and not h.startswith('.')]

# ── HTTPS ────────────────────────────────────────────────────────────────
# Render ends TLS at its proxy and talks plain HTTP to the app. This header
# tells Django the original request was HTTPS; without it SECURE_SSL_REDIRECT
# redirects forever (ERR_TOO_MANY_REDIRECTS).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Start short; raise to a year once HTTPS is known to work, because browsers
# remember this and refuse plain HTTP for the whole period.
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
# Subdomain HSTS and the preload list are for a domain you own. On a shared
# onrender.com address they'd be wrong, so these two warnings are deliberate.
# Revisit both with a custom domain.
SILENCED_SYSTEM_CHECKS = [
    'security.W005', 'security.W021',
    'security.W009',   # see the SECRET_KEY check at the top
]

# ── Database ─────────────────────────────────────────────────────────────
DATABASES = {'default': env.db('DATABASE_URL')}
DATABASES['default']['CONN_MAX_AGE'] = 60          # reuse connections between requests
DATABASES['default']['CONN_HEALTH_CHECKS'] = True  # …but drop ones the server closed

# ── Static files ─────────────────────────────────────────────────────────
# WhiteNoise serves the collected files from gunicorn itself, compressed and
# with hashed names (app.4f3a….css) so they can be cached forever. With
# DEBUG=False Django's own static serving is off: without this, every page
# loads unstyled.
_after_security = MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1
MIDDLEWARE = [
    *MIDDLEWARE[:_after_security],
    'whitenoise.middleware.WhiteNoiseMiddleware',    # straight after SecurityMiddleware
    *MIDDLEWARE[_after_security:],
]
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

# ── Celery ───────────────────────────────────────────────────────────────
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_RESULT_EXPIRES = 3600          # don't let task results fill the 25 MB Redis
CELERY_WORKER_MAX_MEMORY_PER_CHILD = 300_000   # KB; recycle a child before the 512 MB box OOMs

# ── Logging ──────────────────────────────────────────────────────────────
# Render keeps whatever goes to stdout/stderr. With DEBUG=False Django logs
# 500s (with tracebacks) only if a handler is configured — this is it.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '{levelname} {name}: {message}', 'style': '{'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'}},
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', default='INFO')},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
    },
}
