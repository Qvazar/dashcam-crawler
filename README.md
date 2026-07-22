# dashcam-crawler

`dashcam-crawler` is a Python service for automatically collecting dashcam videos from a FitcamX camera when your device is connected to the camera Wi-Fi, then uploading those videos when the device switches back to another network.

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

- Debian/Ubuntu-based Linux system (the Makefile uses `dpkg`/`apt`).
- `sudo` access (required for service install/uninstall).
- Network setup that can connect to both:
  - the dashcam Wi-Fi
  - an upload network (home Wi-Fi, hotspot, etc.)

Python dependencies are installed automatically by `make install` from `requirements.txt`.

## Installation and lifecycle (make + systemd)

### 1) Configure environment file

Create and edit the runtime config:

```bash
cd /path/to/dashcam-crawler
sudo cp ./dashcam-crawler.conf /etc/dashcam-crawler.conf
sudo nano /etc/dashcam-crawler.conf
```

Required values:

- `CAMERA_SSID`: SSID of your dashcam Wi-Fi.
- `TARGET`: upload destination URL (see below).

### 2) Install and start the service

```bash
cd /path/to/dashcam-crawler
make install
```

`make install` will:
- install missing system dependencies
- create a local virtual environment and install Python dependencies
- create system user `dashcam-crawler`
- create `/var/dashcam-crawler`
- install `/etc/dashcam-crawler.conf` if missing
- render and install `dashcam-crawler.service`
- enable and start the systemd service

### 3) Service operations

```bash
sudo systemctl status dashcam-crawler.service
sudo systemctl restart dashcam-crawler.service
sudo journalctl -u dashcam-crawler.service -f
```

### 4) Uninstall

```bash
cd /path/to/dashcam-crawler
make uninstall
```

`make uninstall` stops/disables the service and removes service/user/data/venv resources.  
It keeps `/etc/dashcam-crawler.conf` in place.

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

## Automatic restart and recovery behavior

The installed service is configured for unattended operation:

- `Restart=always`: always restart if the crawler exits.
- `RestartSec=15`: wait 15 seconds between restart attempts.
- `StartLimitBurst=10` and `StartLimitIntervalSec=120`: if too many restarts happen quickly, systemd considers it unstable.
- `StartLimitAction=reboot`: when the start limit is hit, system reboots to recover.
- `KillSignal=SIGTERM` and `TimeoutStopSec=30`: graceful shutdown is attempted before forced termination.

## Wi-Fi prioritization example

See `./wpa_supplicant.conf.example` for an example where:
- camera Wi-Fi has higher priority
- home/hotspot networks are fallback upload networks

## Data written by the crawler

By default (working directory dependent):
- SQLite DB: `./videos.db`
- Downloaded videos: `./videos/`

When installed via `make install`, the service runs as user `dashcam-crawler` with working directory `/var/dashcam-crawler`.

## Configuration reference

`/etc/dashcam-crawler.conf` values:

### Required

- `CAMERA_SSID`  
  Wi-Fi SSID used by the camera. The crawler only crawls/downloads while connected to this SSID.

- `TARGET`  
  Upload destination URL. Supported formats:
  - `gs://bucket-name/optional/prefix`
  - `sftp://host:22/path`

### Optional

- `GOOGLE_APPLICATION_CREDENTIALS`  
  Path to a Google service account JSON key. Needed for `gs://` targets.

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
