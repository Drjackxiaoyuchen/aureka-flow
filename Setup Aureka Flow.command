#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  AUREKA_PYTHON=""
  for candidate in python3.11 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert (3,11) <= sys.version_info[:2] <= (3,12)' 2>/dev/null; then
      AUREKA_PYTHON="$(command -v "$candidate")"
      break
    fi
  done
  if [[ -z "$AUREKA_PYTHON" ]]; then
    echo 'Install Python 3.11 or 3.12, then run this setup again.'
    exit 1
  fi
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv --python "$AUREKA_PYTHON"
  else
    "$AUREKA_PYTHON" -m venv .venv
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -r requirements.lock.txt
else
  .venv/bin/python -m ensurepip --upgrade
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.lock.txt
fi
echo 'Aureka Flow is ready. Double-click Start Aureka Flow.command to open it.'
