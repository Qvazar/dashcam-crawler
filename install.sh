
#!/usr/bin/env bash
set -euo pipefail

DEPS=(wireless-tools iproute2 curl sqlite3 python3 python3-pip python3-venv)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
SERVICE_NAME="fitcamx-crawler.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
PYTHON="$(command -v python3)"

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root."
  exit 1
fi

apt-get update
apt-get install -y "${DEPS[@]}"

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip
if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
  "$VENV_DIR/bin/pip" install -r "$PROJECT_ROOT/requirements.txt"
fi

RUN_FILE="$PROJECT_ROOT/main.py"

if [ -z "$RUN_FILE" ]; then
  echo "No main.py or app.py found in project root."
  exit 1
fi

# TODO Fix this
cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=Fitcamx Crawler
After=network.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_ROOT
ExecStart=$VENV_DIR/bin/python $RUN_FILE
Restart=on-failure
User=root
Environment=PATH=$VENV_DIR/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

