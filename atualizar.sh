#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

git pull --ff-only

if [[ -x "$APP_DIR/.venv/bin/python3" ]]; then
  "$APP_DIR/.venv/bin/python3" -m pip install -r "$APP_DIR/requirements-raspberry.txt"
  "$APP_DIR/.venv/bin/python3" -m py_compile "$APP_DIR/sports_replay_v4.py"
fi

if systemctl is-enabled vibeplay.service >/dev/null 2>&1; then
  sudo systemctl restart vibeplay.service
else
  echo "Feche o VibePlay aberto e execute ./iniciar.sh para carregar as alteracoes."
fi

echo "VibePlay atualizado."
