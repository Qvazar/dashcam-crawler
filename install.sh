#!/usr/bin/env bash
set -euo pipefail

export PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export VENV_DIR="$PROJECT_ROOT/.venv"
export SERVICE_NAME="dashcam-crawler.service"
export SERVICE_DIR="/etc/systemd/system"
export SERVICE_FILE="$SERVICE_DIR/$SERVICE_NAME"
export USER="dashcam-crawler"
export DATA_DIR="/var/dashcam-crawler"

DEPS=(wireless-tools iproute2 curl sqlite3 python3 python3-pip python3-venv)
PYTHON="$(command -v python3)"

#apt-get update
#apt-get install -y "${DEPS[@]}"

# Verify all dependencies are installed
missing_deps=()
for dep in "${DEPS[@]}"; do
  if ! dpkg -l "$dep" 2>/dev/null | grep -q '^ii'; then
    missing_deps+=("$dep")
  fi
done

if [ ${#missing_deps[@]} -gt 0 ]; then
  echo "Error: The following dependencies are missing: ${missing_deps[*]}"
  echo "Please install them using your package manager (e.g., apt-get install ${missing_deps[*]})."
  exit 1
fi

echo "### Setting up user and directories..."
sudo useradd -d "$DATA_DIR" -m "$USER" 2>/dev/null || true
sudo install -d -m 755 -o "$USER" -g "$USER" "$DATA_DIR"

echo "### Setting up configuration..."
if [ ! -f "/etc/dashcam-crawler.conf" ]; then
  sudo install -m 644 "$PROJECT_ROOT/dashcam-crawler.conf" "/etc/dashcam-crawler.conf"
fi

echo "### Setting up virtual environment and installing Python dependencies..."
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON" -m venv "$VENV_DIR"
fi

echo "### Upgrading pip and installing requirements..."
"$VENV_DIR/bin/pip" install --upgrade pip
if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
  "$VENV_DIR/bin/pip" install -r "$PROJECT_ROOT/requirements.txt"
fi

echo "### Setting up systemd service..."
sudo systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
envsubst < "$PROJECT_ROOT/$SERVICE_NAME" | sudo tee "$SERVICE_FILE" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

echo "### Installation complete."
echo "The service '$SERVICE_NAME' has been started and enabled."
echo "Configuration file is located at /etc/dashcam-crawler.conf. Please edit it as needed and restart the service with: systemctl restart $SERVICE_NAME"
echo "Logs can be viewed using: journalctl -u $SERVICE_NAME -f"
