#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

git pull --ff-only

if [[ -x "$APP_DIR/.venv/bin/python3" ]]; then
  "$APP_DIR/.venv/bin/python3" -m pip install -r "$APP_DIR/requirements-raspberry.txt"
fi

if systemctl is-enabled vibeplay.service >/dev/null 2>&1; then
  sudo systemctl restart vibeplay.service
fi

echo "VibePlay atualizado."
