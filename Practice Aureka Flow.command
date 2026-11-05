#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  bash './Setup Aureka Flow.command'
fi
if .venv/bin/python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8772/api/health", timeout=1)' >/dev/null 2>&1; then
  .venv/bin/python -c 'import webbrowser; webbrowser.open("http://127.0.0.1:8772/?practice=1")'
  exit 0
fi
echo 'Opening synthetic FCS practice data on port 8772.'
echo 'Keep this window open while practicing. Press Control-C to stop the server.'
exec .venv/bin/python -m aureka_flow --port 8772 --practice
