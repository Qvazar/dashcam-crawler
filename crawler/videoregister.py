from collections.abc import Iterable
from datetime import datetime
import logging
import sqlite3

from . import debug
from .videorecord import VideoRecord, VideoStatus

DB_FILENAME = "./videos.db"

logger = logging.getLogger(__name__)

sqlite3.register_adapter(datetime, lambda val: val.replace(tzinfo=None).isoformat(timespec='seconds'))
sqlite3.register_converter("DATETIME", lambda val: datetime.fromisoformat(val.decode("utf-8")) if val else None)


class VideoRegister:
    """Handles database operations for video records."""
    
    def __init__(self):
        pass

    @debug.timed
    def _init_database(self):
        """Connects to SQLite using strict power-failure protection settings."""
        logger.debug("Entered _init_database()")

        conn = sqlite3.connect(DB_FILENAME, detect_types=sqlite3.PARSE_DECLTYPES)
        # WAL mode and FULL synchronization protect against corruption during power cuts
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous = FULL;")
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                filename TEXT PRIMARY KEY,
                camera_path TEXT NOT NULL,
                status TEXT NOT NULL, -- uses values from VideoStatus enum
                recorded_at DATETIME NOT NULL,
                marked BOOLEAN DEFAULT 0,
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_marked ON videos(marked) WHERE marked = 1")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_recorded_at ON videos(recorded_at)")
        conn.commit()

        logger.debug("Database initialized and tables created if they did not exist.")
        logger.debug("Exiting _init_database()")

        return conn

    def __enter__(self):
        self._db_conn = self._init_database()
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self._db_conn.close()

    @debug.timed
    def insert_videos(self, videos: Iterable[VideoRecord]):
        """Inserts new video records into the database using VideoRecord instances."""
        logger.debug("Entered insert_videos()")

        with self._db_conn:
            cursor = self._db_conn.executemany('''
                INSERT OR IGNORE INTO videos (filename, camera_path, status, recorded_at, marked)
                VALUES (?, ?, ?, ?, ?)
            ''',
            map(lambda v: (v.filename, v.camera_path, v.status.value, v.recorded_at, v.marked,),
                videos)
            )

            logger.debug("Exiting insert_videos()")
            return cursor.rowcount  # Return the number of rows inserted

    @debug.timed
    def update_videos(self, videos: Iterable[VideoRecord]):
        """Updates the status of a video record in the database."""
        logger.debug("Entered update_videos()")

        with self._db_conn:
            for video in videos:
                self._db_conn.execute('''
                    UPDATE videos
                    SET status = ?
                    WHERE filename = ?
                ''', (video.status.value, video.filename))

        logger.debug("Exiting update_videos()")

    @debug.timed
    def ignore_unmarked_videos(self, marked_window: int):
        """Find videos that are not marked and with a recorded_at outside of the marked window of marked videos' recorded_at and ignore them."""
        logger.debug("Entered ignore_unmarked_videos()")

        with self._db_conn:
            cursor = self._db_conn.execute(
                """
                UPDATE videos
                SET status = ?
                WHERE marked = 0
                    AND status = ?
                    AND NOT EXISTS (
                        SELECT 1 FROM videos AS marked_v
                        WHERE marked_v.marked = 1
                        AND marked_v.status = ?
                        AND datetime(videos.recorded_at) BETWEEN datetime(marked_v.recorded_at, ?) AND datetime(marked_v.recorded_at, ?)
                    )
                """,
                (
                    VideoStatus.IGNORED.value,
                    VideoStatus.FOUND.value,
                    VideoStatus.FOUND.value,
                    f'-{marked_window} minutes',
                    f'+{marked_window} minutes'
                )
            )

            logger.debug("Exiting ignore_unmarked_videos()")
            return cursor.rowcount  # Return the number of rows affected by the update
        
    @debug.timed
    def find_videos_to_download(self, video_recording_window: int = 0):
        """Finds videos that are ready to be downloaded."""
        with self._db_conn:
            # We can never assume to currect datetime from the camera, so allow all videos to finish recording before downloading.
            # This is done by checking if the registered_at is older than a certain window (video_recording_window) from the current db time.
            cursor = self._db_conn.execute(
                """
                SELECT filename, camera_path, status, recorded_at, marked, registered_at
                FROM videos
                WHERE status = ?
                    AND (registered_at <= datetime('now', ?))
                """,
                (VideoStatus.FOUND.value, f'-{video_recording_window} minutes')
            )
            for row in cursor:
                yield VideoRecord(*row)

    @debug.timed
    def find_downloaded_videos(self):
        """Finds videos that have been downloaded and are ready for upload."""
        with self._db_conn:
            cursor = self._db_conn.execute(
                """
                SELECT filename, camera_path, status, recorded_at, marked, registered_at
                FROM videos
                WHERE status = ?
                """,
                (VideoStatus.DOWNLOADED.value,)
            )
            for row in cursor:
                yield VideoRecord(*row)
