#!/usr/bin/env bash
# Start the phone game (scripts/viz/demo.html) and print the links to open on a phone.
#   bash scripts/phone.sh            # phones on the same Wi-Fi, plus a public https link if cloudflared is installed
# The public link (any network, camera mode on iPhone) needs: brew install cloudflared
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
if lsof -ti :"$PORT" >/dev/null 2>&1; then
  echo "  Port $PORT is already in use (an earlier server?). Stop it with:  lsof -ti :$PORT | xargs kill"
  echo "  or use another port:  PORT=8766 bash scripts/phone.sh"
  exit 1
fi
IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
uv run python scripts/viz/server.py --host 0.0.0.0 --port "$PORT" --jobs 2 &
SERVER=$!
TUNNEL=""
trap 'kill $SERVER $TUNNEL 2>/dev/null' EXIT INT TERM
for _ in $(seq 1 60); do
  kill -0 $SERVER 2>/dev/null || { echo "  The server did not start (see the error above)."; exit 1; }
  curl -s -o /dev/null "http://localhost:$PORT/api/challenges" && break
  sleep 1
done
show() {  # a link, and a QR code if qrencode is installed (brew install qrencode)
  echo "  $1"
  command -v qrencode >/dev/null && qrencode -t ANSIUTF8 -m 1 "$2"
}
echo
echo "  LettuceBench phone game is running. Open on the phone:"
show "Same Wi-Fi:   http://$IP:$PORT/demo.html" "http://$IP:$PORT/demo.html"
echo "  (If the page does not load, allow incoming connections for python when macOS asks,"
echo "   or check that the phone is on the same Wi-Fi and not on a guest network.)"
if command -v cloudflared >/dev/null; then
  ( cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT" 2>&1 \
      | grep --line-buffered -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -n 1 \
      | while read -r u; do echo; show "Any network:  $u/demo.html" "$u/demo.html"; echo; done ) &
  TUNNEL=$!
else
  echo "  For a link that works on any network (and the camera mode): brew install cloudflared, then run this again."
fi
echo "  Ctrl+C stops it."
wait $SERVER
