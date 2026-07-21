from .Sftp import Sftp
from .GoogleCloudStorage import GoogleCloudStorage

def get_destination_from_url(url):
    for destination_class in [Sftp, GoogleCloudStorage]:
        if destination_class.supports_url(url):
            return destination_class(url)
    raise ValueError(f"Unsupported target URL: {url}")        
