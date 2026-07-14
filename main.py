import datetime
import email.utils
import logging
import os
import sys
import time
import sqlite3
from enum import Enum
import subprocess
import requests
from bs4 import BeautifulSoup
from google.cloud import storage

# --- ENUMS ---
class VideoStatus(Enum):
    FOUND = "found"
    DOWNLOADED = "downloaded"
    UPLOADED = "uploaded"
    IGNORED = "ignored"
    DELETED = "deleted"

# --- CONFIGURATION ---
CAMERA_SSID = os.environ.get("CAMERA_SSID", None)  # Name of your specific camera WiFi
CAMERA_VIDEO_DIRS = os.environ.get("CAMERA_VIDEO_DIRS", "CARDV/Movie/,CARDV/Movie_E/").split(",")  # Comma-separated list of video directories on the camera
CAMERA_VIDEO_LOCKED_DIRS = os.environ.get("CAMERA_VIDEO_LOCKED_DIRS", "CARDV/EMR/,CARDV/EMR_E/").split(",")  # Directories for locked videos (if applicable)
# Additional minutes to extend the locked video window - will download non-locked videos around locked videos
VIDEO_EXTENDED_LOCK_WINDOW = int(os.environ.get("VIDEO_EXTENDED_LOCK_WINDOW", 0))
VIDEO_RECORDING_WINDOW = int(os.environ.get("VIDEO_RECORDING_WINDOW", 2))  # Minutes to wait before downloading a video that is still being recorded
DOWNLOAD_DIR = os.environ.get("VIDEO_DOWNLOAD_DIR", "/var/fitcamx-crawler/videos")  # Local directory to store downloaded videos
UPLOAD_TARGET= os.environ.get("UPLOAD_TARGET", "gcs")  # Target for uploads (currently only supports 'gcs')
DB_FILE = "/var/fitcamx-crawler/fitcamx-crawler.db"
CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB chunks for download/upload (RAM efficient)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Ensure the download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Validate required environment variables
if not CAMERA_SSID:
    logger.error("CAMERA_SSID environment variable is not set. Exiting.")
    sys.exit(1)


def get_current_ssid():
    """Retrieves the SSID of the WiFi network the Pi is currently connected to."""
    try:
        # Ask Linux network tools for the active SSID
        result = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception as e:
        logger.exception("Unable to retrieve current SSID: %s", e)
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
    conn = sqlite3.connect(DB_FILE)
    # WAL mode and FULL synchronization protect against corruption during power cuts
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous = FULL;")
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            filename TEXT PRIMARY KEY,
            camera_path TEXT NOT NULL,
            status TEXT NOT NULL, -- uses values from VideoStatus enum
            recorded_at TIMESTAMP NOT NULL,
            locked BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    return conn


def get_recorded_at_from_filename(filename):
    """Extracts the recorded timestamp from the video filename, if possible."""
    # Example filename: "20260709112750_036576A.TS" -> recorded_at = "2026-07-09 11:27:50"
    return datetime.strptime(filename[:15], "%Y%m%d%H%M%S")


def crawl_and_download(conn):
    """Connected to the camera WiFi. Find videos and stream them to disk."""
    logger.info("Connected to camera WiFi. Starting crawler...")

    camera_ip = get_network_gateway()
    if not camera_ip:
        logger.error("Could not determine camera address. Aborting crawl.")
        return

    camera_url = f"http://{camera_ip}"


    cursor = conn.cursor()

    # Delete all videos from camera to free up space (only if they are marked as uploaded or ignored in the database)
    cursor.execute("SELECT filename, camera_path FROM videos WHERE status IN (?, ?)", (VideoStatus.UPLOADED.value, VideoStatus.IGNORED.value))
    for filename, camera_path in cursor.fetchall():
        video_deleted = False
        try:
            response = requests.get(f"{camera_url}/{camera_path}?del=1", timeout=10)
            if response.status_code == 404:
                logger.warning(f"Video {camera_path} not found on camera. It may have already been deleted.")
            else:
                response.raise_for_status()
                logger.info(f"Successfully deleted {camera_path} from camera.")
            video_deleted = True
        except Exception:
            # If GET with del=1 failed, try an explicit HTTP DELETE
            try:
                response = requests.delete(f"{camera_url}/{camera_path}", timeout=10)
                if response.status_code == 404:
                    logger.warning(f"Video {camera_path} not found on camera. It may have already been deleted.")
                else:
                    response.raise_for_status()
                    logger.info(f"Successfully deleted {camera_path} from camera using HTTP DELETE.")
                video_deleted = True
            except Exception as e:
                logger.exception("Error during deletion of '%s': %s", camera_path, e)

        if video_deleted:
            cursor.execute("UPDATE videos SET status = ? WHERE filename = ?", (VideoStatus.DELETED.value, filename))
            conn.commit()


    # First download list of all video directories (both normal and locked) to ensure we capture all relevant files
    all_video_dirs = CAMERA_VIDEO_DIRS + CAMERA_VIDEO_LOCKED_DIRS
    for video_dir in all_video_dirs:
        logger.info(f"Crawling video directory: {camera_url}/{video_dir}")
        try:
            response = requests.get(f"{camera_url}/{video_dir}", timeout=10)
            response.raise_for_status()

            camera_time = email.utils.parsedate_to_datetime(response.headers.get('Date'))
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for links ending in .TS (adjust selector based on the website structure)
            for link in soup.find_all('a'):
                href = link.get('href')
                if href and href.endswith('.TS'):
                    # Resolve relative URLs to absolute paths
                    video_url = href if href.startswith('http') else f"{camera_url}{href}"
                    filename = os.path.basename(video_url)
                    video_recorded_at: datetime = get_recorded_at_from_filename(filename)
                    video_locked: bool = video_dir in CAMERA_VIDEO_LOCKED_DIRS

                    # Skip videos that are still being recorded (within the specified window)
                    if camera_time - video_recorded_at < datetime.timedelta(minutes=VIDEO_RECORDING_WINDOW):
                        logger.info(f"Skipping {filename} as it is still being recorded.")
                        continue

                    cursor.execute("INSERT OR IGNORE INTO videos (filename, camera_path, status, recorded_at, locked) VALUES (?, ?, ?, ?)", 
                                    (filename, f"{video_dir}/{filename}", VideoStatus.FOUND.value, video_recorded_at, video_locked))
                    logger.info(f"Registered video: {filename} (Locked: {video_locked})")
        except Exception as e:
            logger.exception("Error during crawling '%s': %s", camera_url, e)

    conn.commit()

    # Find all videos that are not marked as locked and with a recorded_at outside of the locked window of locked videos' recorded_at and ignore them
    cursor.execute(
        """
        UPDATE videos
        SET status = ?
        WHERE locked = 0
            AND status = ?
            AND NOT EXISTS (
                SELECT 1 FROM videos AS locked_v
                WHERE locked_v.locked = 1
                AND locked_v.status = ?
                AND videos.recorded_at BETWEEN datetime(locked_v.recorded_at, ?) AND datetime(locked_v.recorded_at, ?)
            )
        """,
        (
            VideoStatus.IGNORED.value,
            VideoStatus.FOUND.value,
            VideoStatus.FOUND.value,
            f"-{VIDEO_EXTENDED_LOCK_WINDOW} minutes",
            f"+{VIDEO_EXTENDED_LOCK_WINDOW} minutes",
        ),
    )
    conn.commit()
    logger.info("Ignored %s videos that are outside the locked window of locked videos.", cursor.rowcount)

    # Download found videos that are not ignored
    cursor.execute("SELECT filename, camera_path FROM videos WHERE status = ?", (VideoStatus.FOUND.value,))
    for filename, camera_path in cursor.fetchall():
        try:
            local_path = os.path.join(DOWNLOAD_DIR, filename)
            logger.info(f"Downloading {filename} in chunks...")
            
            with requests.get(f"{camera_url}/{camera_path}", stream=True, timeout=15) as video_stream:
                video_stream.raise_for_status()
                with open(local_path, 'wb') as f:
                    for chunk in video_stream.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                    f.flush()
            
            cursor.execute("UPDATE videos SET status = ? WHERE filename = ?", 
                            (VideoStatus.DOWNLOADED.value, filename))
            conn.commit()
            logger.info(f"Successfully downloaded {filename}.")            
        except Exception as e:
            logger.exception("Error during downloading from '%s': %s", video_url, e)


class GcsUploadTarget:
    """Handles uploads to Google Cloud Storage."""
    
    def __init__(self, bucket_name):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
    
    def upload_file(self, local_path, filename):
        """Uploads a file to GCS in chunks."""
        blob = self.bucket.blob(filename, chunk_size=CHUNK_SIZE)
        blob.upload_from_filename(local_path)


class SshUploadTarget:
    """Handles uploads to a remote server via SCP."""
    
    def __init__(self, remote_user, remote_host, remote_path):
        self.remote_user = remote_user
        self.remote_host = remote_host
        self.remote_path = remote_path
    
    def upload_file(self, local_path, filename):
        """Uploads a file to the remote server using SCP."""
        remote_full_path = f"{self.remote_user}@{self.remote_host}:{os.path.join(self.remote_path, filename)}"
        subprocess.run(["scp", local_path, remote_full_path], check=True)


def upload_to_target(conn, upload_target):
    """Phase 2: Connected to internet WiFi. Upload fully downloaded videos to the specified target."""
    logger.info("Connected to internet WiFi. Starting uploads...")
    cursor = conn.cursor()
    
    cursor.execute("SELECT filename FROM videos WHERE status = ?", (VideoStatus.DOWNLOADED.value,))
    videos_to_upload = cursor.fetchall()
    
    if not videos_to_upload:
        logger.info("No videos are currently staged for upload.")
        return

    try:        
        for row in videos_to_upload:
            filename = row[0]
            local_path = os.path.join(DOWNLOAD_DIR, filename)
            
            if not os.path.exists(local_path):
                logger.warning(f"File {filename} is missing from local storage. Resetting status to 'found'.")
                cursor.execute("UPDATE videos SET status = ? WHERE filename = ?", (VideoStatus.FOUND.value, filename))
                conn.commit()
                continue
                
            logger.info(f"Uploading {filename}...")
            upload_target.upload_file(local_path, filename)
            
            # Update database status and immediately delete the local file to free space
            cursor.execute("UPDATE videos SET status = ? WHERE filename = ?", (VideoStatus.UPLOADED.value, filename))
            conn.commit()
            os.remove(local_path)
            logger.info(f"Successfully uploaded {filename} and removed it from local storage.")
            
    except Exception as e:
        logger.exception("Error during upload: %s", e)



def main():
    conn = init_database()

    upload_target = None
    if UPLOAD_TARGET.startswith("gcs://"):
        GCS_BUCKET_NAME = UPLOAD_TARGET[6:]  # Extract bucket name from the URL
        upload_target = GcsUploadTarget(GCS_BUCKET_NAME)
    elif UPLOAD_TARGET.startswith("ssh://"):
        # Example: ssh://user@host:/path/to/upload
        ssh_info = UPLOAD_TARGET[6:]  # Remove 'ssh://'
        user_host, remote_path = ssh_info.split(":", 1)
        remote_user, remote_host = user_host.split("@")
        upload_target = SshUploadTarget(remote_user, remote_host, remote_path)
    else:
        logger.error(f"Unsupported UPLOAD_TARGET: {UPLOAD_TARGET}. Exiting.")
        sys.exit(1)

    
    while True:
        ssid = get_current_ssid()
        logger.info(f"Current WiFi SSID: '{ssid}'")
        
        if ssid == CAMERA_SSID:
            crawl_and_download(conn)
        elif ssid == "":
            logger.info("Not connected to any WiFi network. Waiting...")
        else:
            # Connected to any other WiFi network (e.g., home network or internet hotspot)
            upload_to_target(conn, upload_target)
            
        # Idle sleep interval to avoid unnecessary CPU/battery consumption
        time.sleep(60)

if __name__ == "__main__":
    main()
