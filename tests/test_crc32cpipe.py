import base64

import google_crc32c

from crawler.crc32cpipe import Crc32cPipe


def test_crc32cpipe_accumulates_checksum_and_base64():
    chunks = [b"hello", b" ", b"world"]

    checksum = google_crc32c.Checksum()
    for chunk in chunks:
        checksum.update(chunk)

    pipe = Crc32cPipe(chunks)

    assert list(pipe) == chunks
    assert pipe.get_crc32c() == checksum.digest()
    assert pipe.get_crc32c_base64() == base64.b64encode(checksum.digest()).decode("utf-8")
