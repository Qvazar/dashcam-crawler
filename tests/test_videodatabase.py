"""Tests for crawler/videodatabase.py"""
from datetime import datetime
from unittest.mock import patch

import pytest

from crawler.videorecord import VideoRecord, VideoStatus
from crawler.videodatabase import VideoDatabase


def _make_video(filename, camera_path="/CARDV/MOVIE/", status=VideoStatus.FOUND,
                recorded_at=None, marked=False):
    if recorded_at is None:
        recorded_at = datetime(2026, 7, 9, 11, 0, 0)
    return VideoRecord(filename, camera_path + filename, status, recorded_at, marked)


@pytest.fixture
def db(tmp_path):
    """Return a VideoDatabase backed by a temporary SQLite database."""
    db_path = str(tmp_path / "videos.db")
    with patch("crawler.videodatabase.DB_FILENAME", db_path):
        db = VideoDatabase()
        with db:
            yield db


# ---------------------------------------------------------------------------
# insert_videos
# ---------------------------------------------------------------------------

class TestInsertVideos:
    def test_inserts_single_video(self, db):
        video = _make_video("20260709110000_001A.TS")
        count = db.insert_videos([video])
        assert count == 1

    def test_inserts_multiple_videos(self, db):
        videos = [_make_video(f"2026070911000{i}_00{i}A.TS") for i in range(3)]
        count = db.insert_videos(videos)
        assert count == 3

    def test_ignores_duplicate_filename(self, db):
        video = _make_video("20260709110000_001A.TS")
        db.insert_videos([video])
        count = db.insert_videos([video])
        assert count == 0

    def test_inserted_video_is_retrievable(self, db):
        video = _make_video("20260709110000_001A.TS")
        db.insert_videos([video])
        found = list(db.find_videos_to_download(video_recording_window=0))
        assert len(found) == 1
        assert found[0].filename == video.filename


# ---------------------------------------------------------------------------
# update_videos
# ---------------------------------------------------------------------------

class TestUpdateVideos:
    def test_updates_status(self, db):
        video = _make_video("20260709110000_001A.TS")
        db.insert_videos([video])

        video.status = VideoStatus.DOWNLOADED
        db.update_videos([video])

        downloaded = list(db.find_downloaded_videos())
        assert len(downloaded) == 1
        assert downloaded[0].filename == video.filename

    def test_update_does_not_affect_other_videos(self, db):
        v1 = _make_video("20260709110000_001A.TS")
        v2 = _make_video("20260709120000_002A.TS")
        db.insert_videos([v1, v2])

        v1.status = VideoStatus.DOWNLOADED
        db.update_videos([v1])

        found = list(db.find_videos_to_download(video_recording_window=0))
        assert len(found) == 1
        assert found[0].filename == v2.filename


# ---------------------------------------------------------------------------
# find_videos_to_download
# ---------------------------------------------------------------------------

class TestFindVideosToDownload:
    def test_returns_found_videos(self, db):
        video = _make_video("20260709110000_001A.TS")
        db.insert_videos([video])
        results = list(db.find_videos_to_download(video_recording_window=0))
        assert len(results) == 1

    def test_does_not_return_downloaded_videos(self, db):
        video = _make_video("20260709110000_001A.TS", status=VideoStatus.DOWNLOADED)
        db.insert_videos([video])
        results = list(db.find_videos_to_download(video_recording_window=0))
        assert results == []

    def test_does_not_return_ignored_videos(self, db):
        video = _make_video("20260709110000_001A.TS", status=VideoStatus.IGNORED)
        db.insert_videos([video])
        results = list(db.find_videos_to_download(video_recording_window=0))
        assert results == []

    def test_recording_window_filters_recent_videos(self, db):
        """Videos registered within the recording window must be excluded."""
        video = _make_video("20260709110000_001A.TS")
        db.insert_videos([video])
        # A large window (e.g. 9999 minutes) should exclude the just-inserted video.
        results = list(db.find_videos_to_download(video_recording_window=9999))
        assert results == []


# ---------------------------------------------------------------------------
# find_downloaded_videos
# ---------------------------------------------------------------------------

class TestFindDownloadedVideos:
    def test_returns_downloaded_videos(self, db):
        video = _make_video("20260709110000_001A.TS", status=VideoStatus.DOWNLOADED)
        db.insert_videos([video])
        results = list(db.find_downloaded_videos())
        assert len(results) == 1
        assert results[0].status == VideoStatus.DOWNLOADED

    def test_does_not_return_found_videos(self, db):
        video = _make_video("20260709110000_001A.TS", status=VideoStatus.FOUND)
        db.insert_videos([video])
        results = list(db.find_downloaded_videos())
        assert results == []


# ---------------------------------------------------------------------------
# ignore_unmarked_videos
# ---------------------------------------------------------------------------

class TestIgnoreUnmarkedVideos:
    def test_ignores_unmarked_outside_window(self, db):
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
        db.insert_videos([unmarked, marked])

        # 30-minute window around the marked video (20:00); unmarked (11:00) is far outside
        count = db.ignore_unmarked_videos(marked_window=30)
        assert count == 1

        results = list(db.find_videos_to_download(video_recording_window=0))
        filenames = [v.filename for v in results]
        assert unmarked.filename not in filenames

    def test_keeps_unmarked_within_window(self, db):
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
        db.insert_videos([unmarked, marked])

        count = db.ignore_unmarked_videos(marked_window=10)  # ±10 minutes
        assert count == 0

        results = list(db.find_videos_to_download(video_recording_window=0))
        filenames = [v.filename for v in results]
        assert unmarked.filename in filenames

    def test_does_not_ignore_when_no_marked_videos(self, db):
        videos = [
            _make_video(f"2026070911000{i}_00{i}A.TS", marked=False) for i in range(3)
        ]
        db.insert_videos(videos)
        count = db.ignore_unmarked_videos(marked_window=30)
        assert count == len(videos)
