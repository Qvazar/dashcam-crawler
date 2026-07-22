"""Tests for crawler/videolocalstorage.py"""
import os

import pytest

from crawler.videolocalstorage import _VideoFileStorage, TEMP_FILENAME


class TestVideoFileStorage:
    def test_store_video_creates_file(self, tmp_path):
        storage = _VideoFileStorage(dirname=str(tmp_path))
        data = [b"hello", b" ", b"world"]
        result = storage.store_video("video.TS", iter(data))
        assert os.path.isfile(result)
        assert open(result, "rb").read() == b"hello world"

    def test_store_video_creates_dirname_if_missing(self, tmp_path):
        subdir = tmp_path / "new_subdir"
        storage = _VideoFileStorage(dirname=str(subdir))
        storage.store_video("video.TS", iter([b"data"]))
        assert subdir.is_dir()

    def test_store_video_returns_absolute_path(self, tmp_path):
        storage = _VideoFileStorage(dirname=str(tmp_path))
        result = storage.store_video("video.TS", iter([b"data"]))
        assert os.path.isabs(result)
        assert result.endswith("video.TS")

    def test_store_video_no_temp_file_left(self, tmp_path):
        storage = _VideoFileStorage(dirname=str(tmp_path))
        storage.store_video("video.TS", iter([b"data"]))
        assert not os.path.exists(os.path.join(str(tmp_path), TEMP_FILENAME))

    def test_store_video_empty_chunks_skipped(self, tmp_path):
        """Empty byte strings in the data iterator must be silently ignored."""
        storage = _VideoFileStorage(dirname=str(tmp_path))
        data = [b"first", b"", b"second"]
        result = storage.store_video("video.TS", iter(data))
        assert open(result, "rb").read() == b"firstsecond"

    def test_store_video_overwrites_existing(self, tmp_path):
        storage = _VideoFileStorage(dirname=str(tmp_path))
        storage.store_video("video.TS", iter([b"old"]))
        storage.store_video("video.TS", iter([b"new"]))
        path = storage.get_video_path("video.TS")
        assert open(path, "rb").read() == b"new"

    def test_get_video_path_returns_absolute_path(self, tmp_path):
        storage = _VideoFileStorage(dirname=str(tmp_path))
        storage.store_video("video.TS", iter([b"data"]))
        path = storage.get_video_path("video.TS")
        assert os.path.isabs(path)
        assert path.endswith("video.TS")

    def test_get_video_path_raises_for_missing_file(self, tmp_path):
        storage = _VideoFileStorage(dirname=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            storage.get_video_path("nonexistent.TS")

    def test_delete_video_removes_file(self, tmp_path):
        storage = _VideoFileStorage(dirname=str(tmp_path))
        storage.store_video("video.TS", iter([b"data"]))
        assert os.path.exists(storage.get_video_path("video.TS"))
        storage.delete_video("video.TS")
        assert not os.path.exists(os.path.join(str(tmp_path), "video.TS"))

    def test_delete_video_nonexistent_does_not_raise(self, tmp_path):
        storage = _VideoFileStorage(dirname=str(tmp_path))
        storage.delete_video("nonexistent.TS")  # must not raise
