"""Tests for crawler/videoregister.py"""
from datetime import datetime
from unittest.mock import patch

import pytest

from crawler.videorecord import VideoRecord, VideoStatus
from crawler.videoregister import VideoRegister


def _make_video(filename, camera_path="/CARDV/MOVIE/", status=VideoStatus.FOUND,
                recorded_at=None, marked=False):
    if recorded_at is None:
        recorded_at = datetime(2026, 7, 9, 11, 0, 0)
    return VideoRecord(filename, camera_path + filename, status, recorded_at, marked)


@pytest.fixture
def register(tmp_path):
    """Return a VideoRegister backed by a temporary SQLite database."""
    db_path = str(tmp_path / "videos.db")
    with patch("crawler.videoregister.DB_FILENAME", db_path):
        reg = VideoRegister()
        with reg:
            yield reg


# ---------------------------------------------------------------------------
# insert_videos
# ---------------------------------------------------------------------------

class TestInsertVideos:
    def test_inserts_single_video(self, register):
        video = _make_video("20260709110000_001A.TS")
        count = register.insert_videos([video])
        assert count == 1

    def test_inserts_multiple_videos(self, register):
        videos = [_make_video(f"2026070911000{i}_00{i}A.TS") for i in range(3)]
        count = register.insert_videos(videos)
        assert count == 3

    def test_ignores_duplicate_filename(self, register):
        video = _make_video("20260709110000_001A.TS")
        register.insert_videos([video])
        count = register.insert_videos([video])
        assert count == 0

    def test_inserted_video_is_retrievable(self, register):
        video = _make_video("20260709110000_001A.TS")
        register.insert_videos([video])
        found = list(register.find_videos_to_download(video_recording_window=0))
        assert len(found) == 1
        assert found[0].filename == video.filename


# ---------------------------------------------------------------------------
# update_videos
# ---------------------------------------------------------------------------

class TestUpdateVideos:
    def test_updates_status(self, register):
        video = _make_video("20260709110000_001A.TS")
        register.insert_videos([video])

        video.status = VideoStatus.DOWNLOADED
        register.update_videos([video])

        downloaded = list(register.find_downloaded_videos())
        assert len(downloaded) == 1
        assert downloaded[0].filename == video.filename

    def test_update_does_not_affect_other_videos(self, register):
        v1 = _make_video("20260709110000_001A.TS")
        v2 = _make_video("20260709120000_002A.TS")
        register.insert_videos([v1, v2])

        v1.status = VideoStatus.DOWNLOADED
        register.update_videos([v1])

        found = list(register.find_videos_to_download(video_recording_window=0))
        assert len(found) == 1
        assert found[0].filename == v2.filename


# ---------------------------------------------------------------------------
# find_videos_to_download
# ---------------------------------------------------------------------------

class TestFindVideosToDownload:
    def test_returns_found_videos(self, register):
        video = _make_video("20260709110000_001A.TS")
        register.insert_videos([video])
        results = list(register.find_videos_to_download(video_recording_window=0))
        assert len(results) == 1

    def test_does_not_return_downloaded_videos(self, register):
        video = _make_video("20260709110000_001A.TS", status=VideoStatus.DOWNLOADED)
        register.insert_videos([video])
        results = list(register.find_videos_to_download(video_recording_window=0))
        assert results == []

    def test_does_not_return_ignored_videos(self, register):
        video = _make_video("20260709110000_001A.TS", status=VideoStatus.IGNORED)
        register.insert_videos([video])
        results = list(register.find_videos_to_download(video_recording_window=0))
        assert results == []

    def test_recording_window_filters_recent_videos(self, register):
        """Videos registered within the recording window must be excluded."""
        video = _make_video("20260709110000_001A.TS")
        register.insert_videos([video])
        # A large window (e.g. 9999 minutes) should exclude the just-inserted video.
        results = list(register.find_videos_to_download(video_recording_window=9999))
        assert results == []


# ---------------------------------------------------------------------------
# find_downloaded_videos
# ---------------------------------------------------------------------------

class TestFindDownloadedVideos:
    def test_returns_downloaded_videos(self, register):
        video = _make_video("20260709110000_001A.TS", status=VideoStatus.DOWNLOADED)
        register.insert_videos([video])
        results = list(register.find_downloaded_videos())
        assert len(results) == 1
        assert results[0].status == VideoStatus.DOWNLOADED

    def test_does_not_return_found_videos(self, register):
        video = _make_video("20260709110000_001A.TS", status=VideoStatus.FOUND)
        register.insert_videos([video])
        results = list(register.find_downloaded_videos())
        assert results == []


# ---------------------------------------------------------------------------
# ignore_unmarked_videos
# ---------------------------------------------------------------------------

class TestIgnoreUnmarkedVideos:
    def test_ignores_unmarked_outside_window(self, register):
        unmarked = _make_video(
            "20260709110000_001A.TS",
            recorded_at=datetime(2026, 7, 9, 11, 0, 0),
            marked=False,
        )
        marked = _make_video(
            "20260709200000_002A.TS",
            recorded_at=datetime(2026, 7, 9, 20, 0, 0),
            marked=True,
        )
        register.insert_videos([unmarked, marked])

        # 30-minute window around the marked video (20:00); unmarked (11:00) is far outside
        count = register.ignore_unmarked_videos(marked_window=30)
        assert count == 1

        results = list(register.find_videos_to_download(video_recording_window=0))
        filenames = [v.filename for v in results]
        assert unmarked.filename not in filenames

    def test_keeps_unmarked_within_window(self, register):
        marked_time = datetime(2026, 7, 9, 20, 0, 0)
        unmarked = _make_video(
            "20260709195500_001A.TS",
            recorded_at=datetime(2026, 7, 9, 19, 55, 0),  # 5 minutes before marked
            marked=False,
        )
        marked = _make_video(
            "20260709200000_002A.TS",
            recorded_at=marked_time,
            marked=True,
        )
        register.insert_videos([unmarked, marked])

        count = register.ignore_unmarked_videos(marked_window=10)  # ±10 minutes
        assert count == 0

        results = list(register.find_videos_to_download(video_recording_window=0))
        filenames = [v.filename for v in results]
        assert unmarked.filename in filenames

    def test_does_not_ignore_when_no_marked_videos(self, register):
        videos = [
            _make_video(f"2026070911000{i}_00{i}A.TS", marked=False) for i in range(3)
        ]
        register.insert_videos(videos)
        count = register.ignore_unmarked_videos(marked_window=30)
        assert count == len(videos)
