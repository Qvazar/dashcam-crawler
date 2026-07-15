
#!/usr/bin/env bash
set -euo pipefail

DEPS=(wireless-tools iproute2 curl sqlite3 python3 python3-pip python3-venv)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
SERVICE_NAME="fitcamx-crawler.service"
SERVICE_DIR="$PROJECT_ROOT/systemd"
SERVICE_FILE="$SERVICE_DIR/$SERVICE_NAME"
PYTHON="$(command -v python3)"
USER="fitcamx-crawler"
DATA_DIR="/var/fitcamx-crawler"

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root."
  exit 1
fi

apt-get update
apt-get install -y "${DEPS[@]}"

useradd -d "$DATA_DIR" -m "$USER" 2>/dev/null || true
mkdir -p "$DATA_DIR"
chown "$USER:$USER" "$DATA_DIR"

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip
if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
  "$VENV_DIR/bin/pip" install -r "$PROJECT_ROOT/requirements.txt"
fi

systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
systemctl link "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start "$SERVICE_NAME"
