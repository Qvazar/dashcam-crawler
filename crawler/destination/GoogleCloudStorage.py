import os
from google.cloud import storage


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

    def put(self, file_path, destination_path):
        blob = self.bucket.blob(os.path.join(self.prefix, destination_path) if self.prefix else destination_path)
        blob.upload_from_filename(file_path)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()
