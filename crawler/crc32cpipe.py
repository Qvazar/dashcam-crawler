import base64

import google_crc32c
from typing import Iterable

class Crc32cPipe(Iterable[bytes]):
    def __init__(self, data: Iterable[bytes]):
        self.data = data
        self.checksum = google_crc32c.Checksum()

    def __iter__(self):
        for chunk in self.data:
            self.checksum.update(chunk)
            yield chunk

    def get_crc32c(self):
        return self.checksum.digest()

    def get_crc32c_base64(self):
        return base64.b64encode(self.get_crc32c()).decode("utf-8")
