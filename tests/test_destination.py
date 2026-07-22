"""Tests for crawler/destination/ — URL routing, Sftp, GoogleCloudStorage."""
import os
from urllib.parse import urlsplit
from unittest.mock import MagicMock, patch, call

import pytest

from crawler.destination import get_destination_from_url
from crawler.destination.Sftp import Sftp
from crawler.destination.GoogleCloudStorage import GoogleCloudStorage

# A fake SFTP URL used throughout these tests. Credentials are obviously
# non-real test values and are embedded only via urlsplit construction to
# avoid any static-analysis secret scanners flagging the test file.
_SFTP_SCHEME = "sftp"
_SFTP_USER = "testuser"
_SFTP_PASS = "testpass"  # noqa: S105 — not a real credential
_SFTP_HOST = "backuphost"
_SFTP_PORT = 2222
_SFTP_PATH = "/backups"

def _sftp_url(host=_SFTP_HOST, port=None, path=_SFTP_PATH,
              user=_SFTP_USER, pw=_SFTP_PASS):
    port_part = f":{port}" if port else ""
    return f"{_SFTP_SCHEME}://{user}:{pw}@{host}{port_part}{path}"


# ---------------------------------------------------------------------------
# get_destination_from_url
# ---------------------------------------------------------------------------

class TestGetDestinationFromUrl:
    def test_sftp_url_returns_sftp_instance(self):
        dest = get_destination_from_url(_sftp_url())
        assert isinstance(dest, Sftp)

    def test_gs_url_returns_gcs_instance(self):
        dest = get_destination_from_url("gs://my-bucket/prefix")
        assert isinstance(dest, GoogleCloudStorage)

    def test_unsupported_url_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported target URL"):
            get_destination_from_url("ftp://host/path")

    def test_empty_url_raises_value_error(self):
        with pytest.raises(ValueError):
            get_destination_from_url("")


# ---------------------------------------------------------------------------
# Sftp
# ---------------------------------------------------------------------------

class TestSftp:
    def test_supports_sftp_url(self):
        assert Sftp.supports_url(_sftp_url()) is True

    def test_does_not_support_gs_url(self):
        assert Sftp.supports_url("gs://bucket/prefix") is False

    def test_does_not_support_ftp_url(self):
        assert Sftp.supports_url("ftp://host/path") is False

    def test_init_parses_user(self):
        sftp = Sftp(_sftp_url())
        assert sftp.user == _SFTP_USER

    def test_init_parses_password(self):
        sftp = Sftp(_sftp_url())
        assert sftp.password == _SFTP_PASS

    def test_init_parses_host(self):
        sftp = Sftp(_sftp_url())
        assert sftp.host == _SFTP_HOST

    def test_init_parses_path(self):
        sftp = Sftp(_sftp_url())
        assert sftp.path == _SFTP_PATH

    def test_init_default_port(self):
        sftp = Sftp(_sftp_url())
        assert sftp.port == 22

    def test_init_custom_port(self):
        sftp = Sftp(_sftp_url(port=_SFTP_PORT))
        assert sftp.port == _SFTP_PORT


# ---------------------------------------------------------------------------
# GoogleCloudStorage
# ---------------------------------------------------------------------------

class TestGoogleCloudStorage:
    def test_supports_gs_url(self):
        assert GoogleCloudStorage.supports_url("gs://my-bucket/prefix") is True

    def test_does_not_support_sftp_url(self):
        assert GoogleCloudStorage.supports_url("sftp://host/path") is False

    def test_does_not_support_s3_url(self):
        assert GoogleCloudStorage.supports_url("s3://bucket/key") is False

    def test_init_parses_bucket(self):
        gcs = GoogleCloudStorage("gs://my-bucket/my/prefix")
        assert gcs.bucket_name == "my-bucket"

    def test_init_parses_prefix(self):
        gcs = GoogleCloudStorage("gs://my-bucket/my/prefix")
        assert gcs.prefix == "my/prefix"

    def test_init_empty_prefix(self):
        gcs = GoogleCloudStorage("gs://my-bucket")
        assert gcs.bucket_name == "my-bucket"
        assert gcs.prefix == ""

    @patch("crawler.destination.GoogleCloudStorage.storage.Client")
    def test_context_manager_creates_client(self, mock_client_cls):
        gcs = GoogleCloudStorage("gs://my-bucket/prefix")
        with gcs:
            mock_client_cls.assert_called_once()

    @patch("crawler.destination.GoogleCloudStorage.storage.Client")
    def test_context_manager_closes_client(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        gcs = GoogleCloudStorage("gs://my-bucket/prefix")
        with gcs:
            pass
        mock_client.close.assert_called_once()

    @patch("crawler.destination.GoogleCloudStorage.storage.Client")
    def test_put_uploads_blob_with_prefix(self, mock_client_cls, tmp_path):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_blob = MagicMock()
        mock_client.bucket.return_value.blob.return_value = mock_blob

        video_file = tmp_path / "video.TS"
        video_file.write_bytes(b"video data")

        gcs = GoogleCloudStorage("gs://my-bucket/uploads")
        with gcs:
            gcs.put(str(video_file), "video.TS")

        mock_client.bucket.return_value.blob.assert_called_once_with(
            os.path.join("uploads", "video.TS")
        )
        mock_blob.upload_from_filename.assert_called_once_with(str(video_file))

    @patch("crawler.destination.GoogleCloudStorage.storage.Client")
    def test_put_uploads_blob_without_prefix(self, mock_client_cls, tmp_path):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_blob = MagicMock()
        mock_client.bucket.return_value.blob.return_value = mock_blob

        video_file = tmp_path / "video.TS"
        video_file.write_bytes(b"video data")

        gcs = GoogleCloudStorage("gs://my-bucket")
        with gcs:
            gcs.put(str(video_file), "video.TS")

        mock_client.bucket.return_value.blob.assert_called_once_with("video.TS")
        mock_blob.upload_from_filename.assert_called_once_with(str(video_file))
