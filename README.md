# dashcam-crawler

`dashcam-crawler` is a Python service for automatically collecting dashcam videos from a FitcamX camera when your device is connected to the camera Wi‑Fi, then uploading those videos when the device switches back to another network.

It is designed to run continuously (for example on a Raspberry Pi) and keeps a local SQLite register so videos are only processed once.

## How it works

The crawler loop:

1. Checks the current Wi‑Fi SSID.
2. If connected to the camera SSID:
   - Crawls the camera HTTP file listing.
   - Registers discovered videos in SQLite (`videos.db`).
   - Optionally ignores unmarked videos outside a marked time window.
   - Downloads eligible videos to local storage (`./videos`).
3. If connected to a non-camera network:
   - Uploads downloaded videos to the configured destination.
4. Repeats every `HEARTBEAT_INTERVAL` seconds.

## Requirements

- Linux system with `iwgetid` and `ip` commands available.
- Python 3.10+ (3.11 recommended).
- Network setup that can connect to both:
  - the dashcam Wi‑Fi
  - an upload network (home Wi‑Fi, hotspot, etc.)

Python dependencies are listed in `requirements.txt`:
- `requests`
- `beautifulsoup4`
- `google-cloud-storage`
- `paramiko`

## Quick start (manual run)

### 1) Create virtual environment

```bash
cd /path/to/dashcam-crawler
./setup_venv.sh
```

### 2) Configure environment

Copy the sample config and edit values:

```bash
sudo cp ./dashcam-crawler.conf /etc/dashcam-crawler.conf
sudo nano /etc/dashcam-crawler.conf
```

Minimum required values:

- `CAMERA_SSID`: SSID of your dashcam Wi‑Fi.
- `TARGET`: upload destination URL (see below).

Useful optional values:

- `HEARTBEAT_INTERVAL` (default `60`)
- `VIDEO_RECORDING_WINDOW` (default `2`)
- `VIDEO_EXTENDED_MARKED_WINDOW` (default `0`)
- `VIDEO_EXTENSIONS` (default `.TS`)
- `FITCAMX_MARKED_VIDEO_DIRS` (default `CARDV/EMR/,CARDV/EMR_E/`)

### 3) Run the crawler

```bash
cd /path/to/dashcam-crawler
source .venv/bin/activate
set -a
source /etc/dashcam-crawler.conf
set +a
python -m crawler.main
```

## Upload targets

`TARGET` currently supports:

- Google Cloud Storage: `gs://bucket-name/optional/prefix`
- SFTP: `sftp://host:22/path`

### Google Cloud Storage authentication

Set:

```bash
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

in your config file so the Google client can authenticate.

## Run as a systemd service

This repository includes:
- `dashcam-crawler.service` (template)
- `Makefile` with install/uninstall automation

Install and enable the service:

```bash
cd /path/to/dashcam-crawler
make install
```

Useful commands:

```bash
sudo systemctl status dashcam-crawler.service
sudo systemctl restart dashcam-crawler.service
sudo journalctl -u dashcam-crawler.service -f
```

Uninstall:

```bash
make uninstall
```

## Wi‑Fi prioritization example

See `./wpa_supplicant.conf.example` for an example where:
- camera Wi‑Fi has higher priority
- home/hotspot networks are fallback upload networks

## Data written by the crawler

By default (working directory dependent):
- SQLite DB: `./videos.db`
- Downloaded videos: `./videos/`

When installed via `make install`, the service runs as user `dashcam-crawler` with working directory `/var/dashcam-crawler`.

## Troubleshooting

- **No camera videos found**: verify you are connected to `CAMERA_SSID` and the camera HTTP listing is reachable.
- **No uploads**: verify `TARGET` format and destination credentials.
- **GCS auth errors**: verify `GOOGLE_APPLICATION_CREDENTIALS` path and service account permissions.
- **Service keeps restarting**: check logs with `journalctl` and confirm all required env vars are set in `/etc/dashcam-crawler.conf`.
