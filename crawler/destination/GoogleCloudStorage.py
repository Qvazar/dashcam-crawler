import os
from google.cloud import storage

from crawler.videorecord import VideoRecord

__CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB


class GoogleCloudStorage:
    @staticmethod
    def supports_url(url):
        return url.startswith("gs://")

    def __init__(self, url):
        url = url.replace("gs://", "")
        self.bucket_name = url.split('/')[0]
        self.prefix = '/'.join(url.split('/')[1:])

    def __enter__(self):
        self.client = storage.Client()
        self.bucket = self.client.bucket(self.bucket_name)
        return self

    def put(self, file_path, video: VideoRecord):
        destination_path = video.filename
        
        blob = self.bucket.blob(os.path.join(self.prefix, destination_path) if self.prefix else destination_path, chunk_size=__CHUNK_SIZE)

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
