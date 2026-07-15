#!/usr/bin/env bash
set -euo pipefail

export PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export VENV_DIR="$PROJECT_ROOT/.venv"
export SERVICE_NAME="fitcamx-crawler.service"
export SERVICE_DIR="/etc/systemd/system"
export SERVICE_FILE="$SERVICE_DIR/$SERVICE_NAME"
export USER="fitcamx-crawler"
export DATA_DIR="/var/fitcamx-crawler"

DEPS=(wireless-tools iproute2 curl sqlite3 python3 python3-pip python3-venv)
PYTHON="$(command -v python3)"

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root."
  exit 1
fi

#apt-get update
#apt-get install -y "${DEPS[@]}"

# Verify all dependencies are installed
missing_deps=()
for dep in "${DEPS[@]}"; do
  if ! dpkg -l | grep -q "^ii.*$dep"; then
    missing_deps+=("$dep")
  fi
done

if [ ${#missing_deps[@]} -gt 0 ]; then
  echo "Error: The following dependencies are missing: ${missing_deps[*]}"
  echo "Please install them using your package manager (e.g., apt-get install ${missing_deps[*]})."
  exit 1
fi

echo "Setting up user and directories..."
useradd -d "$DATA_DIR" -m "$USER" 2>/dev/null || true
mkdir -p "$DATA_DIR"
chown "$USER:$USER" "$DATA_DIR"

echo "Setting up configuration..."
if [ ! -f "/etc/fitcamx-crawler.conf" ]; then
  install -m 644 "$PROJECT_ROOT/fitcamx-crawler.conf" "/etc/fitcamx-crawler.conf"
fi

echo "Setting up virtual environment and installing Python dependencies..."
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON" -m venv "$VENV_DIR"
fi

echo "Upgrading pip and installing requirements..."
"$VENV_DIR/bin/pip" install --upgrade pip
if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
  "$VENV_DIR/bin/pip" install -r "$PROJECT_ROOT/requirements.txt"
fi

echo "Setting up systemd service..."
systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
envsubst < "$PROJECT_ROOT/$SERVICE_NAME" > "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start "$SERVICE_NAME"

echo "Installation complete. The service '$SERVICE_NAME' has been started and enabled."
echo "Configuration file is located at /etc/fitcamx-crawler.conf. Please edit it as needed and restart the service."
echo "Logs can be viewed using: journalctl -u $SERVICE_NAME -f"
