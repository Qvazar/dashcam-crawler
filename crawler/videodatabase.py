from collections.abc import Iterable
from datetime import datetime
import sqlite3

from . import debug
from .logging import getLogger
from .videorecord import VideoRecord, VideoStatus

DB_FILENAME = "./videos.db"

logger = getLogger(__name__)

sqlite3.register_adapter(datetime, lambda val: val.replace(tzinfo=None).isoformat(timespec='seconds'))
sqlite3.register_converter("DATETIME", lambda val: datetime.fromisoformat(val.decode("utf-8")) if val else None)


class VideoDatabase:
    """Handles database operations for video records."""

    def __init__(self):
        self._db_conn = None

    @debug.timed
    def _init_database(self):
        """Connects to SQLite using strict power-failure protection settings."""
        logger.debug("Entered _init_database()")

        conn = sqlite3.connect(DB_FILENAME, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.execute("PRAGMA journal_mode=WAL;") # Use Write-Ahead Logging for better crash and power-loss safety
        conn.execute("PRAGMA synchronous = FULL;") # Always write to disk before returning from a transaction to ensure data integrity
        conn.execute("PRAGMA foreign_keys = ON;")  # Ensure foreign key constraints are enforced
        conn.execute("PRAGMA busy_timeout = 5000;")  # Wait up to 5 seconds if the database is locked
        conn.execute("PRAGMA temp_store = MEMORY;")  # Store temporary tables in memory for performance
        conn.execute("PRAGMA mmap_size = 33554432;")  # Allow up to 32 MB of memory-mapped I/O for performance
        conn.execute("PRAGMA threads = 0;") # Do not use any additional threads for SQLite operations.
        conn.execute("PRAGMA trusted_schema = OFF;")  # Disable trusted schema to prevent potential security issues. Also improves performance by avoiding unnecessary checks.
        conn.autocommit = False  # Ensure transactions are committed explicitly
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                filename TEXT PRIMARY KEY,
                camera_path TEXT NOT NULL,
                status TEXT NOT NULL, -- uses values from VideoStatus enum
                recorded_at DATETIME NOT NULL,
                marked BOOLEAN DEFAULT 0,
                crc32c TEXT DEFAULT NULL,
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) WITHOUT ROWID
        ''')

        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_marked ON videos(marked)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_recorded_at ON videos(recorded_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_registered_at ON videos(registered_at)")

        conn.commit()

        self._do_checkpoint(conn)  # Ensure WAL is checkpointed after initialization
        conn.execute("PRAGMA optimize;")  # Optimize the database for performance

        logger.debug("Database initialized and tables created if they did not exist.")
        logger.debug("Exiting _init_database()")

        return conn

    def __enter__(self):
        self._db_conn = self._init_database()
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self._do_checkpoint()  # Ensure WAL is checkpointed before closing
        self._db_conn.close()

    @debug.timed
    def _do_checkpoint(self, conn = None):
        """Perform a WAL checkpoint to ensure all transactions are flushed to the main database file."""
        logger.debug("Performing WAL checkpoint.")

        if conn is None:
            conn = self._db_conn

        conn.execute("PRAGMA wal_checkpoint(RESTART);")

    def checkpoint(self):
        """Returns a context manager that performs a WAL checkpoint on exit."""
        return _CheckpointContextManager(self)

    @debug.timed
    def insert_videos(self, videos: Iterable[VideoRecord]):
        """Inserts new video records into the database using VideoRecord instances."""
        logger.debug("Entered insert_videos()")

        with self._db_conn:
            cursor = self._db_conn.executemany('''
                INSERT OR IGNORE INTO videos (filename, camera_path, status, recorded_at, marked, crc32c)
                VALUES (:filename, :camera_path, :status, :recorded_at, :marked, :crc32c)
            ''',
            map(lambda v: {
                'filename': v.filename,
                'camera_path': v.camera_path,
                'status': v.status.value,
                'recorded_at': v.recorded_at,
                'marked': v.marked,
                'crc32c': v.crc32c
            }, videos)
            )

            logger.debug("Exiting insert_videos()")
            return cursor.rowcount  # Return the number of rows inserted

    @debug.timed
    def update_videos(self, videos: Iterable[VideoRecord]):
        """Updates the status and crc32c of a video record in the database."""
        logger.debug("Entered update_videos()")

        with self._db_conn:
            for video in videos:
                self._db_conn.execute('''
                    UPDATE videos
                    SET status = :status, crc32c = :crc32c
                    WHERE filename = :filename
                ''', {
                    'status': video.status.value,
                    'crc32c': video.crc32c,
                    'filename': video.filename
                })

        logger.debug("Exiting update_videos()")

    @debug.timed
    def ignore_unmarked_videos(self, marked_window: int):
        """Find videos that are not marked and with a recorded_at outside of the marked window of marked videos' recorded_at and ignore them."""
        logger.debug("Entered ignore_unmarked_videos()")

        with self._db_conn:
            cursor = self._db_conn.execute(
                """
                UPDATE videos
                SET status = :status_ignored
                WHERE marked = 0
                    AND status = :status_found
                    AND NOT EXISTS (
                        SELECT 1 FROM videos AS marked_v
                        WHERE marked_v.marked = 1
                        AND marked_v.status = :status_found
                        AND datetime(videos.recorded_at) BETWEEN datetime(marked_v.recorded_at, :marked_window_start) AND datetime(marked_v.recorded_at, :marked_window_end)
                    )
                """,
                {
                    'status_ignored': VideoStatus.IGNORED.value,
                    'status_found': VideoStatus.FOUND.value,
                    'marked_window_start': f'-{marked_window} minutes',
                    'marked_window_end': f'+{marked_window} minutes'
                }
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
                SELECT filename, camera_path, status, recorded_at, marked, crc32c, registered_at
                FROM videos
                WHERE status = :status_found
                    AND (registered_at <= datetime('now', :video_recording_window))
                """,
                {
                    'status_found': VideoStatus.FOUND.value,
                    'video_recording_window': f'-{video_recording_window} minutes'
                }
            )
            for row in cursor:
                yield VideoRecord(*row)

    @debug.timed
    def find_downloaded_videos(self):
        """Finds videos that have been downloaded and are ready for upload."""
        with self._db_conn:
            cursor = self._db_conn.execute(
                """
                SELECT filename, camera_path, status, recorded_at, marked, crc32c, registered_at
                FROM videos
                WHERE status = :status_downloaded
                """,
                {
                    'status_downloaded': VideoStatus.DOWNLOADED.value
                }
            )
            for row in cursor:
                yield VideoRecord(*row)

    def find_uploaded_videos(self):
        """Finds videos that have been uploaded and are ready for deletion."""
        with self._db_conn:
            cursor = self._db_conn.execute(
                """
                SELECT filename, camera_path, status, recorded_at, marked, crc32c, registered_at
                FROM videos
                WHERE status = :status_uploaded_and_deleted
                """,
                {
                    'status_uploaded_and_deleted': VideoStatus.UPLOADED_AND_DELETED.value
                }
            )
            for row in cursor:
                yield VideoRecord(*row)


class _CheckpointContextManager:
    """Context manager for database checkpointing."""
    
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._db._do_checkpoint()

