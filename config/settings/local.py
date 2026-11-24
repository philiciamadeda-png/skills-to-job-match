import os
import sys

from .base import *
import environ

env = environ.Env()

DEBUG = True

DATABASES = {
    'default': env.db('DATABASE_URL')
}

# django-debug-toolbar: query count and timings on every page (dev only).
# Left out under pytest — the toolbar refuses to run in tests.
TESTING = 'PYTEST_VERSION' in os.environ or 'test' in sys.argv
if not TESTING:
    INSTALLED_APPS += ['debug_toolbar']
    MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
    INTERNAL_IPS = ['127.0.0.1']
