#!/usr/bin/env sh
# Let the deployed app use the Ollama on this laptop.
#
#   scripts/ai_tunnel.sh              start the gateway + tunnel, print the URL for Render
#   scripts/ai_tunnel.sh --show-token also print the token (needed once, for Render)
#
# Keep it running while you want the site's AI features to work. Ctrl+C stops both.
# Needs: Ollama running with llama3.2 and nomic-embed-text; cloudflared on PATH.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
TOKEN_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/skills-to-job-match/gateway-token"
PORT="${GATEWAY_PORT:-11435}"
LOG=$(mktemp)

# The token is made once and reused, so Render's OPENAI_API_KEY never needs to change.
if [ ! -s "$TOKEN_FILE" ]; then
  mkdir -p "$(dirname "$TOKEN_FILE")"
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
  echo "Created a new gateway token in $TOKEN_FILE"
fi
OLLAMA_GATEWAY_TOKEN=$(cat "$TOKEN_FILE")
export OLLAMA_GATEWAY_TOKEN GATEWAY_PORT="$PORT"

for model in llama3.2 nomic-embed-text; do
  if ! curl -sf http://127.0.0.1:11434/api/tags | grep -q "\"$model"; then
    echo "Ollama isn't running, or the model '$model' is missing (ollama pull $model)." >&2
    exit 1
  fi
done
command -v cloudflared >/dev/null || { echo "cloudflared not found on PATH." >&2; exit 1; }

python3 "$HERE/ollama_gateway.py" &
GATEWAY=$!
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" > "$LOG" 2>&1 &
TUNNEL=$!
trap 'kill $GATEWAY $TUNNEL 2>/dev/null; rm -f "$LOG"' EXIT INT TERM

URL=''
for _ in $(seq 1 30); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || { echo "Tunnel didn't start:" >&2; cat "$LOG" >&2; exit 1; }

cat <<EOF

  Tunnel is up.  In Render → Environment Groups → skills-shared, set:

    LLM_BASE_URL   = $URL/v1
EOF
if [ "${1:-}" = "--show-token" ]; then
  echo "    OPENAI_API_KEY = $OLLAMA_GATEWAY_TOKEN"
else
  echo "    OPENAI_API_KEY = (unchanged; run with --show-token if you haven't set it yet)"
fi
cat <<EOF

  Save: Render restarts web, worker and beat with the new address.
  The address changes every time this script starts, so update LLM_BASE_URL each time.
  Leave this running. Ctrl+C stops the tunnel.

EOF
wait $TUNNEL
