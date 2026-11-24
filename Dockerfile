# One image for all three processes. Render starts it with a different
# command for each (render.yaml): gunicorn for web, celery worker, celery beat.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

# Dependencies first: this layer is reused until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# collectstatic imports the settings, which require these variables. The values
# are throwaway — only used at build time, never at runtime.
RUN SECRET_KEY=collectstatic-only-placeholder-never-used-at-runtime-0000 DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    python manage.py collectstatic --noinput

# Don't run as root.
RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app

# Render sets PORT. Long timeout: a CV upload calls the language model in the request.
# `exec` makes gunicorn PID 1, so it receives SIGTERM on redeploy and shuts down
# gracefully; without it the shell swallows the signal and gunicorn gets SIGKILLed.
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --threads 2 --timeout 120 --access-logfile -"]
