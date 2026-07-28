import os
import base64
import logging
from google.cloud import storage
import google_crc32c

from crawler.videorecord import VideoRecord

_CHUNK_SIZE = 2 * 1024 * 1024  # 2 MB

logger = logging.getLogger(__name__)

class GoogleCloudStorage:
    @staticmethod
    def supports_url(url):
        return url.startswith("gs://")

    @staticmethod
    def _file_crc32c(file_path):
        checksum = google_crc32c.Checksum()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
                checksum.update(chunk)
        return base64.b64encode(checksum.digest()).decode("utf-8")

    def __init__(self, url):
        url = url.replace("gs://", "")
        self.bucket_name = url.split('/')[0]
        self.prefix = '/'.join(url.split('/')[1:])

    def __enter__(self):
        self.client = storage.Client()
        self.bucket = self.client.bucket(self.bucket_name)
        return self

    def put(self, file_path, video: VideoRecord):
        file_crc32c = self._file_crc32c(file_path)
        destination_path = video.filename
        
        blob = self.bucket.blob(os.path.join(self.prefix, destination_path) if self.prefix else destination_path, chunk_size=_CHUNK_SIZE)

        if blob.exists():
            blob.reload()
            if blob.crc32c == file_crc32c: # Check if existing file is identical
                logger.info(f"File {destination_path} already exists in GCS and is identical. Skipping upload.")
                return
            else:
                logger.info(f"File {destination_path} already exists in GCS but is different. Overwriting.")

        blob.crc32c = file_crc32c  # Set the CRC32C checksum for the new blob
        
        metadata = {
            "Content-Type": "video/mpeg",
            "Custom-Time": video.recorded_at.isoformat(timespec="seconds")
            }

        if video.marked:
            metadata["marked"] = "true"

        blob.metadata = metadata
        blob.upload_from_filename(file_path, timeout=10)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()
