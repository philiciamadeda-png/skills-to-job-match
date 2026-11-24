#!/usr/bin/env python3
"""
A locked door in front of your local Ollama, so the deployed app can use it
through a tunnel without opening Ollama to the whole internet.

    deployed app ──HTTPS──▶ Cloudflare tunnel ──▶ this gateway (127.0.0.1:11435) ──▶ Ollama (127.0.0.1:11434)

- Requires `Authorization: Bearer <OLLAMA_GATEWAY_TOKEN>` on every request.
  The app already sends `Bearer <OPENAI_API_KEY>`, so in production
  OPENAI_API_KEY is set to the same token.
- Forwards only the two endpoints the app uses: chat completions and
  embeddings. Ollama's own API (pull, delete, list models…) is not reachable.
- Never logs request or response bodies: CV text passes through here.

Standard library only. Usually started by scripts/ai_tunnel.sh.
"""
import hmac
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OLLAMA = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434')
LISTEN_PORT = int(os.environ.get('GATEWAY_PORT', '11435'))
TOKEN = os.environ.get('OLLAMA_GATEWAY_TOKEN', '')
ALLOWED = {'/v1/chat/completions', '/v1/embeddings'}
MAX_BODY = 2 * 1024 * 1024        # 2 MB: a CV is a few KB of text
TIMEOUT = 300


class Gateway(BaseHTTPRequestHandler):
    server_version = 'ollama-gateway'
    sys_version = ''

    def _reply(self, status: int, body: bytes, content_type: str = 'application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/healthz':                       # no secrets, no model access
            return self._reply(200, b'ok', 'text/plain')
        self._reply(404, b'{"error": "not found"}')

    def do_POST(self):
        supplied = self.headers.get('Authorization', '').removeprefix('Bearer ').strip()
        if not hmac.compare_digest(supplied.encode(), TOKEN.encode()):
            return self._reply(401, b'{"error": "unauthorized"}')
        if self.path not in ALLOWED:
            return self._reply(404, b'{"error": "not found"}')

        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_BODY:
            return self._reply(413, b'{"error": "request too large"}')
        body = self.rfile.read(length)

        upstream = urllib.request.Request(
            OLLAMA + self.path, data=body, method='POST',
            headers={'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(upstream, timeout=TIMEOUT) as resp:
                self._reply(resp.status, resp.read())
        except urllib.error.HTTPError as exc:            # Ollama answered with an error: pass it on
            self._reply(exc.code, exc.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            self._reply(502, b'{"error": "ollama is not reachable"}')

    def log_message(self, fmt, *args):
        # method, path and status only, never bodies
        sys.stderr.write(f'{self.log_date_time_string()} {fmt % args}\n')


def main():
    if len(TOKEN) < 32:
        sys.exit('Set OLLAMA_GATEWAY_TOKEN to a long random value (32+ characters).')
    server = ThreadingHTTPServer(('127.0.0.1', LISTEN_PORT), Gateway)
    print(f'gateway on http://127.0.0.1:{LISTEN_PORT} → {OLLAMA} (chat + embeddings only)', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
