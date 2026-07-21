from collections.abc import Iterable
import os

from . import debug


TEMP_FILENAME = ".~downloading_video.TS"

class _VideoFileStorage:
    def __init__(self):
        pass

    @debug.timed
    def store_video(self, video_name:str, data:Iterable[bytes]):
        with open(TEMP_FILENAME, 'wb') as f:
            for chunk in data:
                if chunk:
                    f.write(chunk)
            f.flush()
        os.replace(TEMP_FILENAME, video_name)  # Rename temp file to final filename after successful download
        return os.path.abspath(video_name)

    def get_video_path(self, video_name:str):
        path = os.path.abspath(video_name)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Video file {video_name} not found in local storage.")
        return path

    def delete_video(self, video_name:str):
        path = os.path.abspath(video_name)
        if os.path.exists(path):
            os.remove(path)

videolocalstorage = _VideoFileStorage()
