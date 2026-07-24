# dashcam-crawler

`dashcam-crawler` is a Python service for automatically collecting dashcam videos from a FitcamX camera when your device is connected to the camera Wi-Fi, then uploading those videos when the device switches to a non-camera network.

It is designed to run continuously (for example on a Raspberry Pi) and keeps a local SQLite register so videos are only processed once.

## How it works

The crawler loop:

1. Checks the current Wi-Fi SSID.
2. If connected to the camera SSID:
   - Crawls the camera HTTP file listing.
   - Registers discovered videos in SQLite (`videos.db`).
   - Optionally ignores unmarked videos outside a marked time window.
   - Downloads eligible videos to local storage (`./videos`).
3. If connected to a non-camera network:
   - Uploads downloaded videos to the configured destination.
4. Repeats every `HEARTBEAT_INTERVAL` seconds.

## Requirements

- Debian-based Linux with `apt` and Podman packages available (tested on Debian Trixie).
- `sudo` / root access.
- Network setup that can connect to both:
  - the dashcam Wi-Fi
  - an upload network (home Wi-Fi, hotspot, etc.)

The service runs as a [Podman](https://podman.io/) container managed by systemd via a [Quadlet](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html) unit.

## Installation

### 1) Download and run the installer

Before running, review the script:

```bash
curl -fsSL https://raw.githubusercontent.com/Qvazar/dashcam-crawler/main/install.sh -o install.sh
less install.sh          # inspect before running
sudo bash install.sh
```

Or, if you already trust the script:

```bash
curl -fsSL https://raw.githubusercontent.com/Qvazar/dashcam-crawler/main/install.sh | sudo bash
```

The installer will:
- install `podman` if it is not already present
- create a persistent Podman volume `dashcam-crawler-data` for SQLite and downloaded video cache
- interactively prompt for all required and optional configuration values and write `/etc/dashcam-crawler.conf`
- install and enable the systemd Quadlet unit (`/etc/containers/systemd/dashcam-crawler.container`)
- pull the container image from GHCR
- enable `podman-auto-update.timer` so the image is kept up to date automatically (daily)
- start the service

### 2) Edit configuration (if needed after installation)

```bash
sudo nano /etc/dashcam-crawler.conf
sudo systemctl restart dashcam-crawler
```

### 3) Service operations

```bash
systemctl status dashcam-crawler
journalctl -u dashcam-crawler -f
```

### 4) Manual update

The container image is updated automatically every day via `podman-auto-update.timer`.  
To update immediately:

```bash
podman pull ghcr.io/qvazar/dashcam-crawler:latest
systemctl restart dashcam-crawler
```

### 5) Uninstall

```bash
systemctl disable --now dashcam-crawler
sudo rm /etc/containers/systemd/dashcam-crawler.container
sudo systemctl daemon-reload
podman volume rm dashcam-crawler-data
```

> Note: `podman-auto-update.timer` is global for Podman-managed containers. This uninstall flow leaves it enabled to avoid impacting unrelated services on the same host. If this was your only Podman-managed service, you can disable it manually with `systemctl disable --now podman-auto-update.timer`.

`/etc/dashcam-crawler.conf` is left in place so you can re-install without losing your configuration.

## Upload targets

`TARGET` currently supports:

- Google Cloud Storage: `gs://bucket-name/optional/prefix`
- SFTP: `sftp://user:password@host:port/path`

### Google Cloud Storage authentication

The installer will ask for the path to your service account JSON key on the host device and mount it into the container automatically.  Set:

```bash
GOOGLE_APPLICATION_CREDENTIALS=/etc/google-serviceaccount.json
```

in `/etc/dashcam-crawler.conf` (this is the path *inside* the container, which is where the installer mounts the file).
The installer also stores the host path in `GOOGLE_APPLICATION_CREDENTIALS_HOST` so re-runs keep the correct volume mount.

## Automatic restart and recovery behavior

The installed service is configured for unattended operation:

- `Restart=always`: always restart if the crawler exits.
- `RestartSec=15`: wait 15 seconds between restart attempts.
- `StartLimitBurst=10` and `StartLimitIntervalSec=120`: if too many restarts happen quickly, systemd considers it unstable.
- when the start limit is hit, systemd leaves the unit in a failed state until manually restarted (`systemctl restart dashcam-crawler`).
- `KillSignal=SIGTERM` and `TimeoutStopSec=30`: graceful shutdown is attempted before forced termination.

## Raspberry Pi Wi-Fi setup with `nmcli`

On Raspberry Pi systems using NetworkManager, you can manage the Wi-Fi profiles with `nmcli`.

Example connections:

```bash
sudo nmcli connection add \
  type wifi \
  ifname wlan0 \
  con-name dashcam \
  ssid "MyVideoCameraWiFi"

sudo nmcli connection modify dashcam \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "camera-password" \
  connection.autoconnect yes \
  connection.autoconnect-priority 100

sudo nmcli connection add \
  type wifi \
  ifname wlan0 \
  con-name home \
  ssid "MyHomeWiFi"

sudo nmcli connection modify home \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "home-password" \
  connection.autoconnect yes \
  connection.autoconnect-priority 50
```

This gives the camera network higher priority, so the Pi prefers it when the camera is available, and falls back to the home network for uploads when the camera is out of range.

Useful commands:

```bash
nmcli connection show
nmcli device wifi list
nmcli connection up dashcam
nmcli connection up home
```

## Data written by the crawler

The service persists runtime data in the named Podman volume `dashcam-crawler-data`, mounted at `/app/data` inside the container:

- SQLite DB: `/app/data/videos.db`
- Downloaded videos (staged before upload): `/app/data/videos/`

## Configuration reference

`/etc/dashcam-crawler.conf` values:

### Required

- `CAMERA_SSID`  
  Wi-Fi SSID used by the camera. The crawler only crawls/downloads while connected to this SSID.

- `TARGET`  
  Upload destination URL. Supported formats:
  - `gs://bucket-name/optional/prefix`
  - `sftp://user:password@host:port/path`

### Optional

- `GOOGLE_APPLICATION_CREDENTIALS`  
  Path to a Google service account JSON key. Needed for `gs://` targets.

- `GOOGLE_APPLICATION_CREDENTIALS_HOST`  
  Host filesystem path to the same Google service account JSON key. Used by `install.sh` to mount the credentials file into the container on re-runs.

- `HEARTBEAT_INTERVAL` (default: `60`)  
  Main loop sleep interval in seconds. Lower values react faster to network changes; higher values reduce activity.

- `VIDEO_RECORDING_WINDOW` (default: `2`)  
  Minutes to wait before downloading newly discovered files. Helps avoid reading files still being recorded.

- `VIDEO_EXTENDED_MARKED_WINDOW` (default: `0`)  
  Minutes before/after a marked video in which unmarked videos are still kept. Unmarked videos outside this window are set to ignored.

- `VIDEO_EXTENSIONS` (default: `.TS`)  
  Comma-separated video filename extensions to crawl (for example `.TS,.MP4`).

- `FITCAMX_MARKED_VIDEO_DIRS` (default: `CARDV/EMR/,CARDV/EMR_E/`)  
  Comma-separated camera path fragments treated as “marked” event directories.

## Troubleshooting

- **No camera videos found**: verify you are connected to `CAMERA_SSID` and the camera HTTP listing is reachable.
- **No uploads**: verify `TARGET` format and destination credentials.
- **GCS auth errors**: verify `GOOGLE_APPLICATION_CREDENTIALS` path and service account permissions.
- **Service keeps restarting**: check logs with `journalctl` and confirm all required env vars are set in `/etc/dashcam-crawler.conf`.
