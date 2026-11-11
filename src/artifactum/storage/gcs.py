from __future__ import annotations

from pathlib import Path
from typing import Any

from artifactum.exceptions import StorageError
from artifactum.storage.base import Storage


class GCSStorage(Storage):
    """A Google Cloud Storage bucket, reached with Application Default Credentials
    (``gcloud auth application-default login``, or a service account on cloud machines)."""

    scheme = "gs"

    @staticmethod
    def _split(url: str) -> tuple[str, str]:
        """'gs://bucket/a/b' → ('bucket', 'a/b')"""
        bucket, _, blob = url.removeprefix("gs://").partition("/")
        return bucket, blob

    def _client(self) -> Any:
        try:
            from google.cloud import storage
        except ImportError:
            raise StorageError(
                "Storing files in Google Cloud Storage needs an extra package: pip install 'artifactum[gcs]'"
            ) from None
        return storage.Client()

    def _blob(self, url: str) -> Any:
        bucket, blob = self._split(url)
        return self._client().bucket(bucket).blob(blob)

    def check(self) -> None:
        self._client()  # the package is installed; access is checked by the upload itself

    def upload(self, local: Path, url: str) -> None:
        self._blob(url).upload_from_filename(str(local))

    def download(self, url: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._blob(url).download_to_filename(str(local))
        except Exception as e:
            if type(e).__name__ == "NotFound":
                raise StorageError(f"{url} isn't in the bucket.") from None
            raise
