from collections.abc import Iterator
from itertools import chain
import logging
import os
import signal
import sys
import threading

from . import debug
from .network import get_current_ssid
from .source.fitcamx import fitcamx
from .destination import get_destination_from_url
from .videolocalstorage import videolocalstorage
from .videorecord import VideoStatus
from .videoregister import VideoRegister


logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO").upper(), format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger(__name__)


# --- CONFIGURATION ---
class Config:
    """Configuration object for the crawler."""
    
    def __init__(self):
        self.camera_ssid = os.environ.get("CAMERA_SSID", None)
        self.video_extended_marked_window = int(os.environ.get("VIDEO_EXTENDED_MARKED_WINDOW", 0))
        self.video_recording_window = int(os.environ.get("VIDEO_RECORDING_WINDOW", 2))
        self.target = os.environ.get("TARGET", "")
        self.heartbeat_interval = int(os.environ.get("HEARTBEAT_INTERVAL", 60))
        
        self._validate()
    
    def _validate(self):
        """Validate required configuration values."""
        if not self.camera_ssid:
            logger.error("CAMERA_SSID environment variable is not set. Exiting.")
            sys.exit(1)
        
        if not self.target:
            logger.warning("TARGET is not set; uploads will be skipped until it is configured.")
    
    def log_startup(self):
        """Log startup configuration."""
        logger.info("Starting crawler with configuration:\n" \
        "CAMERA_SSID=%s\n" \
        "VIDEO_EXTENDED_MARKED_WINDOW=%d\n" \
        "VIDEO_RECORDING_WINDOW=%d\n" \
        "TARGET=%s\n" \
        "HEARTBEAT_INTERVAL=%d",
        self.camera_ssid,
        self.video_extended_marked_window,
        self.video_recording_window,
        self.target,
        self.heartbeat_interval)


@debug.timed
def register_videos_from_source(video_register, source):
    try:
        video_register.insert_videos(source.find_videos())
    except Exception as e:
        logger.error("Exception when crawling videos: %s", e)

def ignore_unmarked_videos(video_register, extended_marked_window=0):
    try:
        ignored_count = video_register.ignore_unmarked_videos(extended_marked_window)
        logger.info("Ignored %d unmarked videos outside the marked window.", ignored_count)
    except Exception as e:
        logger.error("Exception when ignoring unmarked videos: %s", e)

@debug.timed
def download_videos_from_source(video_register, source, video_recording_window=0):
    downloaded_count = 0
    try:
        for video in video_register.find_videos_to_download(video_recording_window):
            stream: Iterator[bytes] = source.download_video(video)
            videolocalstorage.store_video(video.filename, stream)

            video.status = VideoStatus.DOWNLOADED
            video_register.update_videos([video])
            downloaded_count += 1

            logger.info("Downloaded video: %s", video.filename)
    except Exception as e:
        logger.error("Exception when downloading videos: %s", e)
    finally:
        logger.info("Total downloaded videos: %d", downloaded_count)

@debug.timed
def upload_to_destination(video_register:VideoRegister, destination):
    videos = video_register.find_downloaded_videos()
    first_video = next(videos, None)

    if first_video is None:
        logger.info("No downloaded videos to upload.")
        return

    try:
        logger.info("Uploading downloaded videos to destination.")
        with destination: 
            for v in chain([first_video], videos):
                try:
                    local_path = videolocalstorage.get_video_path(v.filename)
                    
                    logger.debug("Uploading %s...", v.filename)
                    destination.upload_file(local_path, v.filename, v.marked)

                    videolocalstorage.delete_video(v.filename)

                    v.status = VideoStatus.UPLOADED
                    video_register.update_videos([v])

                    logger.info("Successfully uploaded %s and removed it from local storage.", v.filename)
                except FileNotFoundError:
                    logger.warning("File %s is missing from local storage. Resetting status to 'found'.", v.filename)
                    v.status = VideoStatus.FOUND
                    video_register.update_videos([v])
    except Exception as e:
        logger.exception("Error during upload: %s", e)


def _install_shutdown_handler() -> threading.Event:
    shutdown_event = threading.Event()
    def handler(signum, _frame):
        logger.info("Received signal %d. Shutting down gracefully...", signum)
        shutdown_event.set()
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    return shutdown_event


def main():
    config = Config()
    config.log_startup()

    shutdown_event = _install_shutdown_handler()

    source = fitcamx
    destination = get_destination_from_url(config.target) if config.target else None

    ssid = None

    with VideoRegister() as video_register:
        while not shutdown_event.is_set():
            try:
                new_ssid = get_current_ssid()
                if ssid != new_ssid:
                    logger.info("WiFi SSID changed from '%s' to '%s'", ssid, new_ssid)
                    ssid = new_ssid
                
                if ssid is None:
                    logger.debug("No WiFi connection. Waiting...")
                elif ssid == config.camera_ssid:
                        register_videos_from_source(video_register, source)
                        ignore_unmarked_videos(video_register, config.video_extended_marked_window)
                        download_videos_from_source(video_register, source, config.video_recording_window)
                else:
                    if destination:
                        upload_to_destination(video_register, destination)
                        
            except Exception as e:
                logger.exception("Unexpected error: %s", e)

            # Idle sleep interval to avoid unnecessary CPU/battery consumption
            shutdown_event.wait(timeout=config.heartbeat_interval)

    logger.info("Crawler stopped gracefully.")


if __name__ == "__main__":
    main()
