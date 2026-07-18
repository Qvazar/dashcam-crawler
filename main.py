from datetime import datetime, timedelta
import email.utils
import logging
import os
import re
import paramiko
import sys
import time
import sqlite3
from enum import Enum
import subprocess
import requests
from urllib.parse import urlsplit, urlunsplit
from bs4 import BeautifulSoup
from google.cloud import storage


# --- ENUMS ---
class VideoStatus(Enum):
    FOUND = "found"
    DOWNLOADED = "downloaded"
    IGNORED = "ignored"
    UPLOADED = "uploaded"


# --- CONFIGURATION ---
CAMERA_SSID = os.environ.get("CAMERA_SSID", None)  # Name of your specific camera WiFi
CAMERA_MARKED_VIDEO_DIRS = os.environ.get("CAMERA_VIDEO_MARKED_DIRS", "CARDV/EMR/,CARDV/EMR_E/").split(",")  # Directories for marked videos (if applicable)
# Additional minutes to extend the marked video window - will download non-marked videos around marked videos
VIDEO_EXTENSIONS = os.environ.get("VIDEO_EXTENSIONS", ".TS,.MP4").split(",")  # Comma-separated list of video file extensions to consider
VIDEO_EXTENDED_MARKED_WINDOW = int(os.environ.get("VIDEO_EXTENDED_MARKED_WINDOW", 0))
VIDEO_RECORDING_WINDOW = int(os.environ.get("VIDEO_RECORDING_WINDOW", 2))  # Minutes to wait before downloading a video that is still being recorded
VIDEO_DOWNLOAD_DIR = os.environ.get("VIDEO_DOWNLOAD_DIR", "./videos")  # Local directory to store downloaded videos
UPLOAD_TARGET = os.environ.get("UPLOAD_TARGET", "")  # Target for uploads (currently only supports 'gs' and 'ssh' paths)
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", 60))  # Interval in seconds for main heartbeat loop to check WiFi SSID and perform actions

DB_FILENAME = "fitcamx-crawler.db"
CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB chunks for download/upload (RAM efficient)
VIDEO_TEMP_FILENAME = ".~downloading_video.TS"  # Temporary filename for downloading videos before renaming


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Ensure the download directory exists
os.makedirs(VIDEO_DOWNLOAD_DIR, exist_ok=True)

# Validate required environment variables
if not CAMERA_SSID:
    logger.error("CAMERA_SSID environment variable is not set. Exiting.")
    sys.exit(1)

if not UPLOAD_TARGET:
    logger.warning("UPLOAD_TARGET is not set; uploads will be skipped until it is configured.")

if not os.path.isdir(VIDEO_DOWNLOAD_DIR):
    logger.error("VIDEO_DOWNLOAD_DIR is not a directory: %s", VIDEO_DOWNLOAD_DIR)
    sys.exit(1)

if not CAMERA_MARKED_VIDEO_DIRS:
    logger.warning("CAMERA_VIDEO_MARKED_DIRS is empty; marked-video detection will be disabled.")

logger.info(
    "Startup configuration: ssid=%s, download_dir=%s, upload_target=%s, heartbeat=%ss, marked_dirs=%s",
    CAMERA_SSID,
    VIDEO_DOWNLOAD_DIR,
    UPLOAD_TARGET or "<disabled>",
    HEARTBEAT_INTERVAL,
    CAMERA_MARKED_VIDEO_DIRS,
)


def get_current_ssid():
    """Retrieves the SSID of the WiFi network the Pi is currently connected to."""
    try:
        # Ask Linux network tools for the active SSID
        result = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception as e:
        logger.debug("Unable to retrieve current SSID: %s", e)
        return None


def get_network_gateway():
    """Retrieves the gateway IP address of the current network."""
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"], capture_output=True, text=True, check=True
        )
        for line in result.stdout.splitlines():
            if line.startswith("default"):
                parts = line.split()
                gateway_index = parts.index("via") + 1
                return parts[gateway_index]
        return None
    except Exception as e:
        logger.exception("Unable to retrieve network gateway: %s", e)
        return None


def init_database():
    """Connects to SQLite using strict power-failure protection settings."""
    conn = sqlite3.connect(DB_FILENAME)
    # WAL mode and FULL synchronization protect against corruption during power cuts
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous = FULL;")
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            filename TEXT PRIMARY KEY,
            camera_path TEXT NOT NULL,
            status TEXT NOT NULL, -- uses values from VideoStatus enum
            recorded_at TIMESTAMP NOT NULL,
            marked BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_marked ON videos(marked) WHERE marked = 1")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_recorded_at ON videos(recorded_at)")
    conn.commit()
    return conn


def get_recorded_at_from_filename(filename):
    """Extracts the recorded timestamp from the video filename, if possible."""
    # Example filename: "20260709112750_036576A.TS" -> recorded_at = "2026-07-09 11:27:50"
    return datetime.strptime(filename[:15], "%Y%m%d%H%M%S")


def crawl_url(dbconn, url):
    """Crawls a given URL and registers found video files in the database."""
    logger.info(f"Crawling URL: {url}")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link in soup.find_all('a'):
            href = link.get('href')
            if href:
                if any(href.endswith(ext) for ext in VIDEO_EXTENSIONS):
                    video_url = href if href.startswith('http') else f"{url}/{href}"
                    video_path = urlsplit(video_url).path
                    filename = os.path.basename(video_path)
                    video_recorded_at: datetime = get_recorded_at_from_filename(filename)
                    marked = any(dir in video_path for dir in CAMERA_MARKED_VIDEO_DIRS)

                    dbconn.execute(
                        "INSERT OR IGNORE INTO videos (filename, camera_path, status, recorded_at, marked) VALUES (?, ?, ?, ?, ?)", 
                        (filename, video_path, VideoStatus.FOUND.value, video_recorded_at, marked)
                    )
                    logger.debug(f"Registered video: {video_path}")
                elif not re.search(r'^\.?\.?\/?$', href) and not re.search(r'.*\/$', href):  # Ignore '.' and '..' links and non-directory links
                    # Recursively crawl subdirectories
                    crawl_url(dbconn, f"{url}/{href}")
    except Exception as e:
        logger.exception("Error during url crawling '%s': %s", url, e)


def start_crawl_and_download(dbconn):
    """Connected to the camera WiFi. Find videos and stream them to disk."""

    camera_ip = get_network_gateway()
    if camera_ip:
        logger.info(f"Camera IP determined as: {camera_ip}")
    else:
        logger.error("Could not determine camera address. Aborting crawl.")
        return

    camera_url = f"http://{camera_ip}"

    with dbconn:
        crawl_url(dbconn, camera_url)  # Start crawling from the camera's root URL


    # Find all videos that are not marked and with a recorded_at outside of the marked window of marked videos' recorded_at and ignore them
    if CAMERA_MARKED_VIDEO_DIRS:
        with dbconn:
            cursor = dbconn.execute(
                """
                UPDATE videos
                SET status = ?
                WHERE marked = 0
                    AND status = ?
                    AND NOT EXISTS (
                        SELECT 1 FROM videos AS marked_v
                        WHERE marked_v.marked = 1
                        AND marked_v.status = ?
                        AND videos.recorded_at BETWEEN datetime(marked_v.recorded_at, ?) AND datetime(marked_v.recorded_at, ?)
                    )
                """,
                (
                    VideoStatus.IGNORED.value,
                    VideoStatus.FOUND.value,
                    VideoStatus.FOUND.value,
                    f"-{VIDEO_EXTENDED_MARKED_WINDOW} minutes",
                    f"+{VIDEO_EXTENDED_MARKED_WINDOW} minutes",
                ),
            )
            ignored_video_count = cursor.rowcount
            logger.debug("Ignored %s videos that are outside the marked window of marked videos.", ignored_video_count)

    # Download found videos that are not ignored
    # TODO Ignore the last VIDEO_RECORDING_WINDOW minutes of video
    cursor = dbconn.execute("SELECT filename, camera_path FROM videos WHERE status = ?", (VideoStatus.FOUND.value,))
    logger.info(f"Found {cursor.rowcount} videos to download from camera.")
    for filename, camera_path in cursor.fetchall():
        try:
            local_path = os.path.join(VIDEO_DOWNLOAD_DIR, filename)
            video_url = f"{camera_url}/{camera_path}"
            
            with requests.get(f"{video_url}", stream=True, timeout=15) as video_stream:
                video_stream.raise_for_status()
                with open(VIDEO_TEMP_FILENAME, 'wb') as f:
                    for chunk in video_stream.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                    f.flush()
                os.replace(VIDEO_TEMP_FILENAME, local_path)  # Rename temp file to final filename after successful download
            
            dbconn.execute("UPDATE videos SET status = ? WHERE filename = ?", 
                            (VideoStatus.DOWNLOADED.value, filename))
            dbconn.commit()
            logger.info(f"Successfully downloaded {video_url}.")
        except Exception as e:
            logger.exception("Error during downloading from '%s': %s", video_url, e)


class GcsUploadTarget:
    """Handles uploads to Google Cloud Storage."""
    
    def __init__(self, gs_url):
        bucket_name = gs_url[5:]  # Extract bucket name from the URL
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
    
    def upload_file(self, local_path, filename, marked: bool):
        """Uploads a file to GCS in chunks."""
        blob = self.bucket.blob(filename, chunk_size=CHUNK_SIZE)
        blob.metadata = {"marked": str(marked)}
        blob.upload_from_filename(local_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass  # No explicit cleanup needed for GCS


class SshUploadTarget:
    """Handles uploads to a remote server via SCP."""
    
    def __init__(self, ssh_url):
        self.ssh_url = ssh_url

    def open(self):
        _, remote_user, remote_hostname, remote_port, remote_path = re.search(r"^ssh://(?:([^@:/]+)@)?([^:/]+)(?::(\d+))?(?:/(.*))?$", self.ssh_url)

        if not remote_user:
            raise ValueError(f"SSH url must include a user: {self.ssh_url}")

        """Establishes an SSH connection."""
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(remote_hostname, username=remote_user, port=int(remote_port) if remote_port else 22)
        self.sftp = ssh_client.open_sftp()
        if remote_path:
            self.sftp.chdir(remote_path)

    def close(self):
        """Closes the SSH connection."""
        self.sftp.close()

    def upload_file(self, local_path, filename, marked: bool):
        if marked:
            # Append "_marked" to the filename before uploading
            filename = os.path.splitext(filename)[0] + "_marked" + os.path.splitext(filename)[1]

        self.sftp.put(local_path, filename)

    def __enter__(self):
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def upload_to_target(dbconn):
    upload_target = None
    if UPLOAD_TARGET.startswith("gs://"):
        upload_target = GcsUploadTarget(UPLOAD_TARGET)
    elif UPLOAD_TARGET.startswith("ssh://"):
        # Example: ssh://user@host:/path/to/upload
        upload_target = SshUploadTarget(UPLOAD_TARGET)
    else:
        logger.error(f"Unsupported UPLOAD_TARGET: {UPLOAD_TARGET}.")
        raise ValueError(f"Unsupported UPLOAD_TARGET: {UPLOAD_TARGET}")


    """Phase 2: Connected to internet WiFi. Upload fully downloaded videos to the specified target."""
    cursor = dbconn.execute("SELECT filename, marked FROM videos WHERE status = ?", (VideoStatus.DOWNLOADED.value,))
    videos = cursor.fetchall()
    videos_count = len(videos)

    if videos_count == 0:
        logger.debug("No videos are currently staged for upload.")
        return

    logger.info(f"Preparing to upload {videos_count} videos to target: {UPLOAD_TARGET}")

    try:
        with upload_target: 
            for filename, marked in videos:
                local_path = os.path.join(VIDEO_DOWNLOAD_DIR, filename)
                
                if not os.path.exists(local_path):
                    logger.warning(f"File {filename} is missing from local storage. Resetting status to 'found'.")
                    dbconn.execute("UPDATE videos SET status = ? WHERE filename = ?", (VideoStatus.FOUND.value, filename))
                    dbconn.commit()
                    continue
                    
                logger.debug(f"Uploading {filename}...")
                upload_target.upload_file(local_path, filename, marked)
                
                # Update database status and immediately delete the local file to free space
                os.remove(local_path)
                dbconn.execute("UPDATE videos SET status = ? WHERE filename = ?", (VideoStatus.UPLOADED.value, filename))
                dbconn.commit()
                logger.info(f"Successfully uploaded {filename} and removed it from local storage.")            
    except Exception as e:
        logger.exception("Error during upload: %s", e)


def main():
    ssid = None
    while True:
        new_ssid = get_current_ssid()
        if ssid != new_ssid:
            logger.info(f"WiFi SSID changed from '{ssid}' to '{new_ssid}'")
            ssid = new_ssid
        
        if ssid == CAMERA_SSID:
            conn = init_database()
            try:
                start_crawl_and_download(conn)
            finally:
                conn.close()
        elif ssid == None:
            logger.debug("No WiFi connection. Waiting...")
        else:
            conn = init_database()
            try:
                upload_to_target(conn)
            finally:
                conn.close()
            
        # Idle sleep interval to avoid unnecessary CPU/battery consumption
        time.sleep(HEARTBEAT_INTERVAL)  # Sleep for the specified interval before checking again

if __name__ == "__main__":
    main()
