#!/usr/bin/env bash
# Dashcam Crawler — Container Installation Script
#
# Usage:
#   sudo bash install.sh
#
# Or download and run in one step:
#   curl -fsSL https://raw.githubusercontent.com/Qvazar/dashcam-crawler/main/install.sh | sudo bash
#
# Requirements: Debian Trixie (or later), sudo/root access.

set -euo pipefail

# Allow overriding the image for testing or pinned deployments:
#   DASHCAM_IMAGE=ghcr.io/qvazar/dashcam-crawler:v1.2.3 sudo bash install.sh
IMAGE="${DASHCAM_IMAGE:-ghcr.io/qvazar/dashcam-crawler:latest}"

SERVICE_NAME="dashcam-crawler"
CONFIG_FILE="/etc/dashcam-crawler.conf"
DATA_VOLUME="dashcam-crawler-data"
QUADLET_DIR="/etc/containers/systemd"

# Set by setup_config; used by write_quadlet to add a GCS volume mount.
GCS_HOST_PATH=""

# ── Helpers ───────────────────────────────────────────────────────────────────

info() { printf '\033[1;32m[INFO]\033[0m  %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m  %s\n' "$*"; }
die()  { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

# ask PROMPT [DEFAULT]
# Prints a prompt and returns the user's input, falling back to DEFAULT.
ask() {
    local prompt="$1" default="${2-}" reply
    if [[ -n "$default" ]]; then
        read -rp "  $prompt [$default]: " reply
    else
        read -rp "  $prompt: " reply
    fi
    printf '%s' "${reply:-$default}"
}

# ── Root check ────────────────────────────────────────────────────────────────

check_root() {
    [[ $EUID -eq 0 ]] || die "This script must be run as root.  Try: sudo bash install.sh"
}

# ── Install podman ────────────────────────────────────────────────────────────

install_podman() {
    if command -v podman &>/dev/null; then
        info "Podman already installed: $(podman --version)"
        return
    fi
    info "Installing podman..."
    apt-get update -qq
    apt-get install -y --no-install-recommends podman
}

# ── Persistent volume ─────────────────────────────────────────────────────────

setup_volume() {
    if podman volume exists "$DATA_VOLUME"; then
        info "Podman volume already exists: $DATA_VOLUME"
        return
    fi
    info "Creating Podman volume: $DATA_VOLUME"
    podman volume create "$DATA_VOLUME" >/dev/null
}

# ── Configuration setup ───────────────────────────────────────────────────────

setup_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        info "Config already exists at $CONFIG_FILE — keeping existing file."
        info "Edit it manually and run: systemctl restart $SERVICE_NAME"
        local target_from_config
        target_from_config=$(grep -E '^TARGET=' "$CONFIG_FILE" | cut -d= -f2- || true)

        # Read GCS host path for Quadlet volume mount.
        GCS_HOST_PATH=$(grep -E '^GOOGLE_APPLICATION_CREDENTIALS_HOST=' "$CONFIG_FILE" \
            | cut -d= -f2- || true)
        if [[ "$target_from_config" == gs://* ]] && [[ -z "$GCS_HOST_PATH" ]]; then
            warn "Existing config has a GCS target but no GOOGLE_APPLICATION_CREDENTIALS_HOST entry."
            GCS_HOST_PATH=$(ask "Path to GCS credentials file on host" "/etc/dashcam-crawler/google-serviceaccount.json")
            echo "GOOGLE_APPLICATION_CREDENTIALS_HOST=$GCS_HOST_PATH" >> "$CONFIG_FILE"
        fi
        return
    fi

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "   Dashcam Crawler — Configuration Setup"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # ── Required ──────────────────────────────────────────────────────────────

    local camera_ssid=""
    while [[ -z "$camera_ssid" ]]; do
        camera_ssid=$(ask "CAMERA_SSID  Wi-Fi SSID of your dashcam (required)")
        [[ -z "$camera_ssid" ]] && echo "  CAMERA_SSID is required — please enter a value."
    done

    # ── Upload target ─────────────────────────────────────────────────────────

    echo ""
    echo "  TARGET: where to upload videos after leaving the camera network."
    echo "  Supported formats:"
    echo "    gs://bucket-name/optional/prefix   — Google Cloud Storage"
    echo "    sftp://user@host:port/path          — SFTP"
    echo "  Leave empty to skip uploads (you can set TARGET later)."
    local target
    target=$(ask "TARGET" "")

    # ── GCS credentials ───────────────────────────────────────────────────────

    local gcs_creds_line=""
    if [[ "$target" == gs://* ]]; then
        echo ""
        echo "  A Google Cloud Storage target requires a service account JSON key."
        echo "  Provide the path to that file on this device."
        GCS_HOST_PATH=$(ask "Path to GCS credentials file on host" "/etc/dashcam-crawler/google-serviceaccount.json")
        # The container always mounts the file to /etc/google-serviceaccount.json.
        gcs_creds_line="GOOGLE_APPLICATION_CREDENTIALS=/etc/google-serviceaccount.json"
        if [[ ! -f "$GCS_HOST_PATH" ]]; then
            warn "File not found at $GCS_HOST_PATH"
            warn "Copy your service account JSON there before starting the service."
        fi
    fi

    # ── Optional settings ─────────────────────────────────────────────────────

    echo ""
    echo "  Optional settings — press Enter to accept the defaults:"
    local heartbeat rec_window marked_window extensions marked_dirs
    heartbeat=$(ask    "HEARTBEAT_INTERVAL (main loop sleep, seconds)" "60")
    rec_window=$(ask   "VIDEO_RECORDING_WINDOW (minutes before downloading new files)" "2")
    marked_window=$(ask "VIDEO_EXTENDED_MARKED_WINDOW (minutes around marked videos to keep)" "0")
    extensions=$(ask   "VIDEO_EXTENSIONS (comma-separated)" ".TS,.MP4")
    marked_dirs=$(ask  "FITCAMX_MARKED_VIDEO_DIRS (comma-separated)" "CARDV/EMR/,CARDV/EMR_E/")

    # ── Write config ──────────────────────────────────────────────────────────

    info "Writing $CONFIG_FILE..."
    {
        echo "CAMERA_SSID=$camera_ssid"
        [[ -n "$target" ]]           && echo "TARGET=$target"
        [[ -n "$GCS_HOST_PATH" ]]    && echo "GOOGLE_APPLICATION_CREDENTIALS_HOST=$GCS_HOST_PATH"
        [[ -n "$gcs_creds_line" ]]   && echo "$gcs_creds_line"
        echo "HEARTBEAT_INTERVAL=$heartbeat"
        echo "VIDEO_RECORDING_WINDOW=$rec_window"
        echo "VIDEO_EXTENDED_MARKED_WINDOW=$marked_window"
        echo "VIDEO_EXTENSIONS=$extensions"
        echo "FITCAMX_MARKED_VIDEO_DIRS=$marked_dirs"
    } > "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
    info "Configuration written to $CONFIG_FILE"
}

# ── Quadlet container unit ────────────────────────────────────────────────────

write_quadlet() {
    mkdir -p "$QUADLET_DIR"
    local unit_file="$QUADLET_DIR/$SERVICE_NAME.container"
    info "Writing Quadlet unit $unit_file..."
    {
        cat <<EOF
[Unit]
Description=Dashcam Crawler
After=network.target
StartLimitBurst=10
StartLimitIntervalSec=120

[Container]
Image=$IMAGE
Network=host
EnvironmentFile=$CONFIG_FILE
Volume=$DATA_VOLUME:/app/data
AutoUpdate=registry
EOF
        if [[ -n "$GCS_HOST_PATH" ]]; then
            echo "Volume=$GCS_HOST_PATH:/etc/google-serviceaccount.json:ro,z"
        fi
        cat <<'EOF'

[Service]
Restart=always
RestartSec=15
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF
    } > "$unit_file"
}

# ── Pull image ────────────────────────────────────────────────────────────────

pull_image() {
    info "Pulling $IMAGE..."
    podman pull "$IMAGE"
}

# ── Automatic updates ─────────────────────────────────────────────────────────

enable_auto_update() {
    info "Enabling podman-auto-update.timer (checks for image updates daily)..."
    systemctl enable --now podman-auto-update.timer
}

# ── Start the service ─────────────────────────────────────────────────────────

start_service() {
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        info "Stopping existing $SERVICE_NAME instance..."
        systemctl stop "$SERVICE_NAME"
    fi
    info "Reloading systemd daemon..."
    systemctl daemon-reload
    info "Enabling and starting $SERVICE_NAME..."
    systemctl enable --now "$SERVICE_NAME"
}

# ── Main ──────────────────────────────────────────────────────────────────────

main() {
    check_root
    install_podman
    setup_volume
    setup_config
    write_quadlet
    pull_image
    enable_auto_update
    start_service

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "   ✓  Dashcam Crawler installed successfully!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  Status:      systemctl status $SERVICE_NAME"
    echo "  Logs:        journalctl -u $SERVICE_NAME -f"
    echo "  Config:      sudo nano $CONFIG_FILE"
    echo "  Data volume: podman volume inspect $DATA_VOLUME"
    echo "  Restart:     systemctl restart $SERVICE_NAME"
    echo ""
    echo "  Auto-updates are enabled via podman-auto-update.timer (runs daily)."
    echo "  To update manually:"
    echo "    podman pull $IMAGE && systemctl restart $SERVICE_NAME"
    echo ""
}

main
