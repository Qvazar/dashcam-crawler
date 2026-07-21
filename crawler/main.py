import logging
import os
import sys
import time

from . import debug
from .network import get_current_ssid
from .source.fitcamx import fitcamx
from .target import get_target_from_url
from .videolocalstorage import videolocalstorage
from .videorecord import VideoStatus
from .videoregister import VideoRegister


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


# --- CONFIGURATION ---
class Config:
    """Configuration object for the crawler."""
    
    def __init__(self):
        self.camera_ssid = os.environ.get("CAMERA_SSID", None)
        self.video_extended_marked_window = int(os.environ.get("VIDEO_EXTENDED_MARKED_WINDOW", 0))
        self.video_recording_window = int(os.environ.get("VIDEO_RECORDING_WINDOW", 2))
        self.video_download_dir = os.environ.get("VIDEO_DOWNLOAD_DIR", "./videos")
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
        
        if not os.path.isdir(self.video_download_dir):
            logger.error("VIDEO_DOWNLOAD_DIR is not a directory: %s", self.video_download_dir)
            sys.exit(1)
        
        os.makedirs(self.video_download_dir, exist_ok=True)
    
    def log_startup(self):
        """Log startup configuration."""
        logger.info("Starting crawler with configuration:\n" \
        "CAMERA_SSID=%s\n" \
        "VIDEO_EXTENDED_MARKED_WINDOW=%d\n" \
        "VIDEO_RECORDING_WINDOW=%d\n" \
        "VIDEO_DOWNLOAD_DIR=%s\n" \
        "TARGET=%s\n" \
        "HEARTBEAT_INTERVAL=%d",
        self.camera_ssid,
        self.video_extended_marked_window,
        self.video_recording_window,
        self.video_download_dir,
        self.target,
        self.heartbeat_interval)


config = Config()
config.log_startup()

@debug.timed
def register_videos_from_source(video_register, source):
    try:
        video_register.insert_videos(source.find_videos())
    except Exception as e:
        logger.error(f"Exception when crawling videos: %s", e)

def ignore_unmarked_videos(video_register):
    try:
        ignored_count = video_register.ignore_unmarked_videos(config.video_extended_marked_window)
        logger.info(f"Ignored {ignored_count} unmarked videos outside the marked window.")
    except Exception as e:
        logger.error(f"Exception when ignoring unmarked videos: %s", e)

@debug.timed
def download_videos_from_source(video_register, source):
    downloaded_count = 0
    try:
        for video in video_register.find_videos_to_download(config.video_recording_window):
            for video_stream in source.download_video(video):
                videolocalstorage.store_video(video.filename, video_stream)

                video.status = VideoStatus.DOWNLOADED
                video_register.update_videos([video])
                downloaded_count += 1

                logger.info(f"Downloaded video: {video.filename}")
    except Exception as e:
        logger.error(f"Exception when downloading videos: %s", e)
    finally:
        logger.info(f"Total downloaded videos: {downloaded_count}")

@debug.timed
def upload_to_target(video_register:VideoRegister, target):
    videos = video_register.find_downloaded_videos()

    try:
        with target: 
            for v in videos:
                try:
                    local_path = videolocalstorage.get_video_path(v.filename)
                    
                    logger.debug(f"Uploading {v.filename}...")
                    target.upload_file(local_path, v.filename, v.marked)

                    videolocalstorage.delete_video(v.filename)

                    v.status = VideoStatus.UPLOADED
                    video_register.update_videos([v])

                    logger.info(f"Successfully uploaded {v.filename} and removed it from local storage.")
                except FileNotFoundError:
                    logger.warning(f"File {v.filename} is missing from local storage. Resetting status to 'found'.")
                    v.status = VideoStatus.FOUND
                    video_register.update_videos([v])
    except Exception as e:
        logger.exception("Error during upload: %s", e)


def main():
    source = fitcamx
    target = get_target_from_url(config.target)

    ssid = None
    while True:
        new_ssid = get_current_ssid()
        if ssid != new_ssid:
            logger.info(f"WiFi SSID changed from '{ssid}' to '{new_ssid}'")
            ssid = new_ssid
        
        if ssid == config.camera_ssid:
            with VideoRegister() as video_register:
                register_videos_from_source(video_register, source)
                ignore_unmarked_videos(video_register)
                download_videos_from_source(video_register, source)
        elif ssid == None:
            logger.debug("No WiFi connection. Waiting...")
        else:
            with VideoRegister() as video_register:
                upload_to_target(video_register, target)
            
        # Idle sleep interval to avoid unnecessary CPU/battery consumption
        time.sleep(config.heartbeat_interval)  # Sleep for the specified interval before checking again

if __name__ == "__main__":
    main()
