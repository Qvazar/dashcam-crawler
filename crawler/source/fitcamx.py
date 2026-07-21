from collections.abc import Iterable
from datetime import datetime
import logging
import os
import re
from typing import Iterator
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
import requests
from ..debug import timed
from ..network import get_network_gateway
from ..videorecord import VideoRecord, VideoStatus

logger = logging.getLogger(__name__)

FITCAMX_MARKED_VIDEO_DIRS = os.environ.get("FITCAMX_MARKED_VIDEO_DIRS", "CARDV/EMR/,CARDV/EMR_E/").split(",")  # Directories for marked videos (if applicable)
VIDEO_EXTENSIONS = os.environ.get("VIDEO_EXTENSIONS", ".TS").split(",")  # Comma-separated list of video file extensions to consider


def _datetime_from_filename(filename) -> datetime:
    """Extracts the recorded timestamp from the video filename, if possible."""
    # Example filename: "20260709112750_036576A.TS" -> recorded_at = "2026-07-09 11:27:50"
    return datetime.strptime(filename[:15], "%Y%m%d%H%M%S")

def _get_camera_url() -> str:
    camera_ip = get_network_gateway()
    if camera_ip:
        return f"http://{camera_ip}"
    raise RuntimeError("Could not determine camera address from network gateway")


def _crawl_url(url: str):
    """Crawls a given URL and yields found videos."""
    logger.info(f"Crawling URL: {url}")

    response = requests.get(url, timeout=10)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    for link in soup.find_all('a'):
        href = link.get('href')
        if href:
            found_url = urljoin(url, href)
            if any(href.endswith(ext) for ext in VIDEO_EXTENSIONS):
                video_path = urlsplit(found_url).path
                filename = os.path.basename(video_path)
                video_recorded_at: datetime = _datetime_from_filename(filename)
                marked = any(dir in video_path for dir in FITCAMX_MARKED_VIDEO_DIRS)

                logger.debug(f"Found video: {video_path}")

                yield VideoRecord(filename, video_path, VideoStatus.FOUND, video_recorded_at, marked)
            elif not re.search(r'^\.\.?\/?$', href) and not re.search(r'.*\/$', href):
                # Ignore '.' and '..' links and non-directory links
                # Recursively crawl subdirectories
                yield from _crawl_url(found_url)


class _FitcamXSource:
    def __init__(self):
        pass

    @timed
    def find_videos(self):
        camera_url = _get_camera_url()
        logger.info(f"Camera URL determined as: {camera_url}")
        return _crawl_url(camera_url)

    @timed
    def download_video(self, video: VideoRecord) -> Iterator[bytes]:
        """Download videos from the camera and yield their content in chunks."""
        camera_url = _get_camera_url()
        video_url = urljoin(camera_url, video.camera_path)
        with requests.get(video_url, stream=True, timeout=15) as video_stream:
            video_stream.raise_for_status()
            return video_stream.iter_content(chunk_size=2*1024*1024)  # Yield the video stream in chunks for the video


fitcamx = _FitcamXSource()
