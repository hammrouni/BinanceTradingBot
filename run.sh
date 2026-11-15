#!/usr/bin/env bash
# Quick local start: venv + deps + dashboard (no Docker needed).
# Usage: ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

pip install -q -r requirements.txt
cp -n .env.example .env || true

exec python main.py
