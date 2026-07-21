from .SftpTarget import SftpTarget
from .GoogleStorageTarget import GoogleStorageTarget

def get_target_from_url(url):
    for target_class in [SftpTarget, GoogleStorageTarget]:
        if target_class.supports_url(url):
            return target_class(url)
    raise ValueError(f"Unsupported target URL: {url}")        
