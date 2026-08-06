from datetime import datetime, timedelta
import logging
import os
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


def _log_crawl_url_response_to_file(url: str, response: requests.Response):
    """Log the response of a crawl URL to a file for debugging purposes."""
    if logger.isEnabledFor(logging.DEBUG):
        log_dir = os.path.join(os.getcwd(), "fitcamx_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, f"{datetime.now().isoformat(timespec='seconds')}_{urlsplit(url).path}.log")
        
        with open(log_file_path, "w", encoding="utf-8") as log_file:
            log_file.write(f"URL: {url}\n")
            log_file.write(f"Status Code: {response.status_code}\n")
            log_file.write("Response Content:\n")
            log_file.write(response.text)
        
        logger.debug(f"fitcamx response logged to {log_file_path}")


def _datetime_from_filename(filename) -> datetime:
    """Extracts the recorded timestamp from the video filename, if possible."""
    # Example filename: "20260709112750_036576A.TS" -> recorded_at = "2026-07-09 11:27:50"
    return datetime.strptime(filename[:14], "%Y%m%d%H%M%S")

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
    links = soup.find_all('a')

    logger.debug(f"Received response from {url} with status code {response.status_code} and found {len(links)} links.")
    _log_crawl_url_response_to_file(url, response)
    
    for link in links:
        href = link.get('href')
        if href:
            found_url = urljoin(url, href)

            logger.debug(f"Found link: {found_url}")

            if any(href.endswith(ext) for ext in VIDEO_EXTENSIONS):
                video_path = urlsplit(found_url).path
                filename = os.path.basename(video_path)
                video_recorded_at: datetime = _datetime_from_filename(filename)
                marked = any(dir in video_path for dir in FITCAMX_MARKED_VIDEO_DIRS)

                logger.debug(f"Found video: {video_path}")

                yield VideoRecord(filename, video_path, VideoStatus.FOUND, video_recorded_at, marked)
            elif href.find(".") == -1:  # Likely a directory (no file extension)
                # Recursively crawl subdirectories
                logger.debug(f"Found directory: {found_url}, recursing into it.")
                yield from _crawl_url(found_url)


def _guess_time_offset(videos: list[VideoRecord]) -> timedelta:
    """Guess the time offset between camera clock and real time.

    Compares the latest video's recorded timestamp to the current time, rounded
    to the nearest hour (the camera clock is typically off by a whole number of
    hours due to winter/summer time differences).  Returns a timedelta to add to
    each video's recorded_at so that it approximates real wall-clock time.
    """
    if not videos:
        return timedelta(0)
    latest = max(videos, key=lambda v: v.recorded_at)
    now = datetime.now()
    raw_offset = now - latest.recorded_at
    # Round to the nearest whole hour
    total_seconds = raw_offset.total_seconds()
    rounded_hours = round(total_seconds / 3600)
    offset = timedelta(hours=rounded_hours)
    if offset:
        logger.info(
            "Guessed camera time offset: %s (raw diff: %s, based on latest video %s)",
            offset,
            raw_offset,
            latest.filename,
        )
    return offset


class _FitcamXSource:
    def __init__(self):
        pass

    @timed
    def find_videos(self):
        camera_url = _get_camera_url()
        logger.info(f"Camera URL determined as: {camera_url}")
        videos = list(_crawl_url(camera_url))
        offset = _guess_time_offset(videos)
        if offset:
            for v in videos:
                v.recorded_at += offset
        return iter(videos)

    @timed
    def download_video(self, video: VideoRecord) -> Iterator[bytes]:
        """Download videos from the camera and yield their content in chunks."""
        camera_url = _get_camera_url()
        video_url = urljoin(camera_url, video.camera_path)
        with requests.get(video_url, stream=True, timeout=15) as video_stream:
            if video_stream.status_code == 404:
                raise FileNotFoundError(f"Video {video.filename} not found at {video_url}")
            
            video_stream.raise_for_status()
            yield from video_stream.iter_content(chunk_size=2*1024*1024)  # Yield the video stream in chunks for the video


fitcamx = _FitcamXSource()
