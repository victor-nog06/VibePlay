#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
ENABLE_SERVICE=false

if [[ "${1:-}" == "--enable-service" ]]; then
  ENABLE_SERVICE=true
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Este instalador deve ser executado no Linux."
  exit 1
fi

echo "Instalando pacotes do sistema..."
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  python3-opencv python3-pyqt6 python3-pygame \
  ffmpeg git \
  libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0

echo "Criando ambiente Python..."
python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/python3" -m pip install --upgrade pip
"$VENV_DIR/bin/python3" -m pip install -r "$APP_DIR/requirements-raspberry.txt"

mkdir -p \
  "$APP_DIR/replays" \
  "$APP_DIR/uploads/pendentes" \
  "$APP_DIR/temp" \
  "$APP_DIR/config" \
  "$APP_DIR/logs" \
  "$APP_DIR/auth"

if [[ ! -f "$APP_DIR/config/vibe_config.json" ]]; then
  cp "$APP_DIR/config/vibe_config.example.json" "$APP_DIR/config/vibe_config.json"
fi

chmod +x "$APP_DIR/iniciar.sh" "$APP_DIR/atualizar.sh"

if [[ "$ENABLE_SERVICE" == true ]]; then
  CURRENT_USER="$(id -un)"
  USER_HOME="$(getent passwd "$CURRENT_USER" | cut -d: -f6)"
  SERVICE_TMP="$(mktemp)"

  sed \
    -e "s|@USER@|$CURRENT_USER|g" \
    -e "s|@HOME@|$USER_HOME|g" \
    -e "s|@APP_DIR@|$APP_DIR|g" \
    "$APP_DIR/systemd/vibeplay.service.template" > "$SERVICE_TMP"

  sudo install -m 0644 "$SERVICE_TMP" /etc/systemd/system/vibeplay.service
  rm -f "$SERVICE_TMP"
  sudo systemctl daemon-reload
  sudo systemctl enable vibeplay.service

  echo "Servico instalado e habilitado. Para iniciar agora:"
  echo "  sudo systemctl start vibeplay"
fi

echo
echo "Instalacao concluida."
echo "Edite config/vibe_config.json e execute: ./iniciar.sh"
