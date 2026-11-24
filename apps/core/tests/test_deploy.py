"""
Production configuration: settings pass Django's deploy checks, the health
check works behind a proxy, and the AI endpoints come from settings.
"""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

ROOT = Path(__file__).resolve().parents[3]


def _production(code: str, **env) -> subprocess.CompletedProcess:
    """Run Python with production settings, as the container would (no .env values leak in)."""
    full_env = {
        'PATH': os.environ['PATH'],
        'DJANGO_SETTINGS_MODULE': 'config.settings.production',
        'SECRET_KEY': 'x' * 64 + 'prod-check-not-a-real-secret',
        'DATABASE_URL': 'sqlite:////tmp/prod-check.sqlite3',
        'RENDER_EXTERNAL_HOSTNAME': 'skills-web.onrender.com',
        'ALLOWED_HOSTS': '',
        **env,
    }
    return subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=full_env,
                          capture_output=True, text=True, timeout=120)


def test_production_settings_pass_deploy_checks():
    result = _production(
        'import django, sys; django.setup()\n'
        'from django.core.management import call_command\n'
        'call_command("check", deploy=True, fail_level="WARNING")\n'
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_production_hosts_https_and_static():
    result = _production(
        'import django; django.setup()\n'
        'from django.conf import settings as s\n'
        'print(s.DEBUG, s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS, s.SECURE_PROXY_SSL_HEADER, '
        's.STORAGES["staticfiles"]["BACKEND"], s.MIDDLEWARE[:3])\n',
        ALLOWED_HOSTS='jobs.example.com',
    )
    assert result.returncode == 0, result.stderr[-2000:]
    out = result.stdout
    assert out.startswith('False ')
    assert "['jobs.example.com', 'skills-web.onrender.com']" in out
    assert "'https://skills-web.onrender.com'" in out
    assert "('HTTP_X_FORWARDED_PROTO', 'https')" in out
    assert 'whitenoise.storage.CompressedManifestStaticFilesStorage' in out
    # health check first, then security, then whitenoise
    assert ("['apps.core.middleware.HealthCheckMiddleware', 'django.middleware.security.SecurityMiddleware', "
            "'whitenoise.middleware.WhiteNoiseMiddleware']") in out


@pytest.mark.parametrize('key', ['', 'changeme'])
def test_production_refuses_to_start_without_a_real_secret_key(key):
    result = _production('import django; django.setup()', SECRET_KEY=key)
    assert result.returncode != 0
    assert 'SECRET_KEY must be set' in result.stderr


def test_production_accepts_a_render_generated_key():
    import base64
    render_style = base64.b64encode(os.urandom(32)).decode()      # 256 bits → 44 characters
    assert len(render_style) == 44
    result = _production(
        'import django; django.setup()\n'
        'from django.core.management import call_command\n'
        'call_command("check", deploy=True, fail_level="WARNING")\n',
        SECRET_KEY=render_style,
    )
    assert result.returncode == 0, result.stderr[-2000:]


# ── Health check ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_health_check_ignores_host_header_and_redirects(client, settings):
    settings.ALLOWED_HOSTS = ['skills-web.onrender.com']
    settings.SECURE_SSL_REDIRECT = True
    resp = client.get('/healthz/', HTTP_HOST='10.214.3.7:10000')
    assert resp.status_code == 200
    assert resp.content == b'ok'


@pytest.mark.django_db
def test_health_check_fails_when_database_is_down(client):
    with patch('apps.core.middleware.connection') as conn:
        conn.cursor.side_effect = RuntimeError('connection refused')
        resp = client.get('/healthz/')
    assert resp.status_code == 503


# ── AI endpoints come from settings ───────────────────────────────────────

def _fake_embeddings_response(n):
    resp = MagicMock()
    # Returned out of order on purpose: results must be put back in input order
    resp.json.return_value = {'data': [{'index': i, 'embedding': [float(i)] * 3} for i in reversed(range(n))]}
    return resp


@override_settings(EMBED_BASE_URL='https://api.openai.com/v1/', EMBED_DIMENSIONS=768, OPENAI_API_KEY='sk-test')
def test_embed_batch_uses_settings_and_keeps_order():
    from apps.intelligence import tasks
    with patch.object(tasks, 'requests') as req:
        req.post.return_value = _fake_embeddings_response(3)
        vectors = tasks._embed_batch(['a', 'b', 'c'])

    url = req.post.call_args.args[0]
    kwargs = req.post.call_args.kwargs
    assert url == 'https://api.openai.com/v1/embeddings'
    assert kwargs['json'] == {'model': tasks.EMBED_MODEL, 'input': ['a', 'b', 'c'], 'dimensions': 768}
    assert kwargs['headers'] == {'Authorization': 'Bearer sk-test'}
    assert vectors == [[0.0] * 3, [1.0] * 3, [2.0] * 3]


@override_settings(EMBED_BASE_URL='http://localhost:11434/v1', EMBED_DIMENSIONS=None, OPENAI_API_KEY='')
def test_embed_batch_local_ollama_sends_no_dimensions():
    from apps.intelligence import tasks
    with patch.object(tasks, 'requests') as req:
        req.post.return_value = _fake_embeddings_response(1)
        tasks._embed_batch(['a'])
    assert 'dimensions' not in req.post.call_args.kwargs['json']
    assert req.post.call_args.args[0] == 'http://localhost:11434/v1/embeddings'


@override_settings(LLM_MODEL='gpt-4o-mini')
def test_llm_model_comes_from_settings():
    from apps.intelligence.llm.client import LLMClient
    assert LLMClient().model == 'gpt-4o-mini'
    assert LLMClient(model='llama3.2').model == 'llama3.2'
