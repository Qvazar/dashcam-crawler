# AGENTS.md

## Repository overview
- `dashcam-crawler` is a Python service that watches for a FitCamX dashcam Wi-Fi network, crawls video files from the camera, stores them locally, and uploads them to a configured destination.
- The main runtime entrypoint is `/home/runner/work/dashcam-crawler/dashcam-crawler/crawler/main.py`.
- Production deployment is managed with systemd units and a Debian/Ubuntu-oriented `Makefile`.

## Important paths
- `/home/runner/work/dashcam-crawler/dashcam-crawler/crawler/main.py` — main loop, config parsing, signal handling, crawl/download/upload orchestration
- `/home/runner/work/dashcam-crawler/dashcam-crawler/crawler/source/fitcamx.py` — FitCamX HTTP crawling and video download logic
- `/home/runner/work/dashcam-crawler/dashcam-crawler/crawler/destination/` — upload backends (`Sftp.py`, `GoogleCloudStorage.py`)
- `/home/runner/work/dashcam-crawler/dashcam-crawler/crawler/videoregister.py` — SQLite-backed video state tracking
- `/home/runner/work/dashcam-crawler/dashcam-crawler/crawler/videolocalstorage.py` — local file staging
- `/home/runner/work/dashcam-crawler/dashcam-crawler/Makefile` — install, uninstall, dependency, and venv automation
- `/home/runner/work/dashcam-crawler/dashcam-crawler/dashcam-crawler.conf` — example environment configuration
- `/home/runner/work/dashcam-crawler/dashcam-crawler/dashcam-crawler.service` and restart units — systemd templates

## Local development workflow
1. Create the virtualenv and install Python dependencies:
   - `cd /home/runner/work/dashcam-crawler/dashcam-crawler`
   - `./setup_venv.sh`
2. Activate the environment when running tools manually:
   - `source .venv/bin/activate`
3. Run the crawler from the repository root with module execution:
   - `PYTHONPATH=/home/runner/work/dashcam-crawler/dashcam-crawler .venv/bin/python -m crawler.main`

## Runtime and configuration notes
- Required configuration is loaded from environment variables or `/etc/dashcam-crawler.conf` in the systemd deployment.
- `CAMERA_SSID` is required; `TARGET` is optional but must be set for uploads.
- Supported destination resolution currently comes from URL schemes handled in `crawler/destination/__init__.py`.
- The video register uses SQLite with WAL mode and stores state in `videos.db` relative to the working directory.
- The service unit sets `WorkingDirectory=${DATA_DIR}` and `PYTHONPATH=${PROJECT_ROOT}`.

## Validation guidance
- Python dependencies are listed in `/home/runner/work/dashcam-crawler/dashcam-crawler/requirements.txt`.
- Repository automation is exposed through:
  - `make check-deps`
  - `make venv`
  - `make install`
  - `make uninstall`
- There is currently no dedicated automated test suite in the repository, so validate changes with the smallest relevant command set and by reviewing affected runtime paths carefully.

## Change guidelines
- Prefer small, targeted edits; avoid changing systemd units or install flow unless the task specifically requires deployment changes.
- Keep configuration names and runtime behavior aligned across `crawler/main.py`, `dashcam-crawler.conf`, and the systemd unit templates.
- When changing source crawling or upload behavior, review both the state transitions in `videoregister.py` and the local file lifecycle in `videolocalstorage.py`.
