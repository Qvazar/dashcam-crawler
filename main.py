import os
import sys
import time
import sqlite3
import subprocess
import requests
from bs4 import BeautifulSoup
from google.cloud import storage

# --- CONFIGURATION ---
DEVICE_WIFI_SSID = "MyVideoCameraWiFi"  # Name of your specific camera WiFi
DB_FILE = "crawler_state.db"
DOWNLOAD_DIR = os.environ.get("VIDEO_DOWNLOAD_DIR", "downloads")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "your-gcs-bucket-name")
CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB chunks for download/upload (RAM efficient)

# Ensure the download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def get_current_ssid():
    """Retrieves the SSID of the WiFi network the Pi is currently connected to."""
    try:
        # Ask Linux network tools for the active SSID
        result = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception:
        return ""

def init_database():
    """Connects to SQLite using strict power-failure protection settings."""
    conn = sqlite3.connect(DB_FILE)
    # WAL mode and FULL synchronization protect against corruption during power cuts
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous = FULL;")
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            url TEXT PRIMARY KEY,
            filename TEXT,
            status TEXT, -- 'found', 'downloaded', 'uploaded'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    return conn

def crawl_and_download(conn):
    """Phase 1: Connected to the camera WiFi. Find videos and stream them to disk."""
    print("Connected to camera WiFi. Starting crawler...")
    cursor = conn.cursor()
    
    # REPLACE THIS WITH THE ACTUAL URL OF YOUR DEVICE'S WEB INTERFACE
    camera_url = "http://192.168.1" 
    
    try:
        response = requests.get(camera_url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for links ending in .mp4 (adjust selector based on the website structure)
        for link in soup.find_all('a'):
            href = link.get('href')
            if href and href.endswith('.mp4'):
                # Resolve relative URLs to absolute paths
                video_url = href if href.startswith('http') else f"http://192.168.1{href}"
                filename = os.path.basename(video_url)
                
                # Check if this video is already registered in the database
                cursor.execute("SELECT status FROM videos WHERE url = ?", (video_url,))
                row = cursor.fetchone()
                
                if not row:
                    # Atomically register the new video discovery
                    cursor.execute("INSERT INTO videos (url, filename, status) VALUES (?, ?, 'found')", (video_url, filename))
                    conn.commit()
                    status = 'found'
                else:
                    status = row[0]
                
                # If the video is only marked as "found", proceed to stream-download it
                if status == 'found':
                    local_path = os.path.join(DOWNLOAD_DIR, filename)
                    print(f"Downloading {filename} in chunks...")
                    
                    with requests.get(video_url, stream=True, timeout=15) as video_stream:
                        video_stream.raise_for_status()
                        with open(local_path, 'wb') as f:
                            for chunk in video_stream.iter_content(chunk_size=CHUNK_SIZE):
                                if chunk:
                                    f.write(chunk)
                                    # Force Linux to physically write the data to the SD card
                                    os.fsync(f.fileno()) 
                    
                    cursor.execute("UPDATE videos SET status = 'downloaded' WHERE url = ?", (video_url,))
                    conn.commit()
                    print(f"Successfully downloaded {filename}.")
                    
    except Exception as e:
        print(f"Error during crawling or downloading: {e}")

def upload_to_gcs(conn):
    """Phase 2: Connected to internet WiFi. Upload fully downloaded videos to the cloud."""
    print("Connected to internet WiFi. Starting Google Cloud Storage uploads...")
    cursor = conn.cursor()
    
    cursor.execute("SELECT url, filename FROM videos WHERE status = 'downloaded'")
    videos_to_upload = cursor.fetchall()
    
    if not videos_to_upload:
        print("No videos are currently staged for upload.")
        return

    try:
        # Initializes the GCS client (relies on the GOOGLE_APPLICATION_CREDENTIALS environment variable)
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        
        for video_url, filename in videos_to_upload:
            local_path = os.path.join(DOWNLOAD_DIR, filename)
            
            if not os.path.exists(local_path):
                print(f"Warning: File {filename} is missing from local storage. Resetting status to 'found'.")
                cursor.execute("UPDATE videos SET status = 'found' WHERE url = ?", (video_url,))
                conn.commit()
                continue
                
            print(f"Uploading {filename} to GCS...")
            blob = bucket.blob(filename)
            
            # Setting chunk_size explicitly activates a 'resumable upload', saving memory
            blob.chunk_size = CHUNK_SIZE 
            blob.upload_from_filename(local_path)
            
            # Update database status and immediately delete the local file to free space
            cursor.execute("UPDATE videos SET status = 'uploaded' WHERE url = ?", (video_url,))
            conn.commit()
            os.remove(local_path)
            print(f"Successfully uploaded {filename} and removed it from local storage.")
            
    except Exception as e:
        print(f"Error during GCS upload: {e}")

def main():
    conn = init_database()
    
    while True:
        ssid = get_current_ssid()
        print(f"Current WiFi SSID: '{ssid}'")
        
        if ssid == DEVICE_WIFI_SSID:
            crawl_and_download(conn)
        elif ssid == "":
            print("Not connected to any WiFi network. Waiting...")
        else:
            # Connected to any other WiFi network (e.g., home network or internet hotspot)
            upload_to_gcs(conn)
            
        # Idle sleep interval to avoid unnecessary CPU/battery consumption
        time.sleep(30)

if __name__ == "__main__":
    main()
