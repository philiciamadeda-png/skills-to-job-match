from django.db import connection
from django.http import HttpResponse

HEALTH_PATH = '/healthz/'


class HealthCheckMiddleware:
    """
    Answer the platform's health check before anything else runs.

    It sits first in MIDDLEWARE so the check never hits ALLOWED_HOSTS (the
    checker may use an internal address as Host → 400) or the HTTPS redirect
    (→ 301). Returns 200 only if the database answers, so a deploy whose
    database is unreachable is marked unhealthy instead of serving errors.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != HEALTH_PATH:
            return self.get_response(request)
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception as exc:
            return HttpResponse(f'database unavailable: {exc.__class__.__name__}', status=503,
                                content_type='text/plain')
        return HttpResponse('ok', content_type='text/plain')
