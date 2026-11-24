"""
scripts/ollama_gateway.py: the token check and endpoint allow-list in front
of the laptop's Ollama. Runs the real gateway against a fake Ollama.
"""
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

TOKEN = 't' * 48
SCRIPT = Path(__file__).resolve().parents[3] / 'scripts' / 'ollama_gateway.py'


def _load_gateway():
    spec = importlib.util.spec_from_file_location('ollama_gateway', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeOllama(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        FakeOllama.seen.append((self.path, self.headers.get('Authorization')))
        reply = json.dumps({'path': self.path, 'echo': json.loads(body)}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args):
        pass


def _serve(handler):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def gateway():
    gw = _load_gateway()
    ollama = _serve(FakeOllama)
    gw.OLLAMA = f'http://127.0.0.1:{ollama.server_port}'
    gw.TOKEN = TOKEN
    gw.Gateway.log_message = lambda *a: None
    server = _serve(gw.Gateway)
    FakeOllama.seen = []
    yield gw, f'http://127.0.0.1:{server.server_port}', ollama
    server.shutdown()
    ollama.shutdown()


def _post(url, token=None, body=b'{"model": "llama3.2"}'):
    headers = {'Content-Type': 'application/json'}
    if token is not None:
        headers['Authorization'] = f'Bearer {token}'
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.mark.parametrize('token', [None, '', 'wrong', TOKEN[:-1]])
def test_requests_without_the_right_token_are_refused(gateway, token):
    _, base, _ = gateway
    status, _ = _post(base + '/v1/chat/completions', token)
    assert status == 401
    assert FakeOllama.seen == []                                  # never reached Ollama


@pytest.mark.parametrize('path', ['/api/pull', '/api/delete', '/api/tags', '/api/generate', '/v1/models'])
def test_only_chat_and_embeddings_are_forwarded(gateway, path):
    _, base, _ = gateway
    status, _ = _post(base + path, TOKEN)
    assert status == 404
    assert FakeOllama.seen == []


@pytest.mark.parametrize('path', ['/v1/chat/completions', '/v1/embeddings'])
def test_allowed_endpoints_reach_ollama_without_the_token(gateway, path):
    _, base, _ = gateway
    status, body = _post(base + path, TOKEN)
    assert status == 200
    assert json.loads(body) == {'path': path, 'echo': {'model': 'llama3.2'}}
    assert FakeOllama.seen == [(path, None)]                      # token not passed on


def test_ollama_down_is_a_502_so_the_app_retries_later(gateway):
    gw, base, ollama = gateway
    ollama.shutdown()
    ollama.server_close()
    status, _ = _post(base + '/v1/embeddings', TOKEN)
    assert status == 502


def test_oversized_request_is_refused_before_reading_it(gateway):
    import http.client
    gw, base, _ = gateway
    conn = http.client.HTTPConnection(base.removeprefix('http://'), timeout=10)
    conn.putrequest('POST', '/v1/embeddings')
    conn.putheader('Authorization', f'Bearer {TOKEN}')
    conn.putheader('Content-Length', str(gw.MAX_BODY + 1))     # declared, never sent
    conn.endheaders()
    assert conn.getresponse().status == 413
    assert FakeOllama.seen == []
