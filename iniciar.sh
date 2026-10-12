#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"

mkdir -p \
  "$APP_DIR/replays" \
  "$APP_DIR/uploads/pendentes" \
  "$APP_DIR/temp" \
  "$APP_DIR/config" \
  "$APP_DIR/logs" \
  "$APP_DIR/auth"

if [[ ! -x "$VENV_DIR/bin/python3" ]]; then
  echo "Ambiente Python nao encontrado. Execute primeiro: ./instalar_raspberry.sh"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg nao encontrado. Instale com: sudo apt install ffmpeg"
  exit 1
fi

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-dummy}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"

echo "[$(date --iso-8601=seconds)] Iniciando VibePlay" >> "$APP_DIR/logs/runtime.log"
exec "$VENV_DIR/bin/python3" "$APP_DIR/sports_replay_v4.py" >> "$APP_DIR/logs/runtime.log" 2>&1
