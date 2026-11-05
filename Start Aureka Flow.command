#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  bash './Setup Aureka Flow.command'
fi
if .venv/bin/python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=1)' >/dev/null 2>&1; then
  echo 'Aureka Flow is already running at http://127.0.0.1:8765'
  .venv/bin/python -c 'import webbrowser; webbrowser.open("http://127.0.0.1:8765")'
  exit 0
fi
echo 'Starting Aureka Flow. Keep this window open; press Control-C to stop.'
exec .venv/bin/python -m aureka_flow
