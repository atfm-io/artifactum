"""Where artifact files live. The registry records only each file's URL; this package
puts files at those URLs and fetches them back.

    base.py    Storage, the interface, plus everything every backend shares
    local.py   LocalStorage: a directory, usually shared (file:///groups/lab/atfm)
    gcs.py     GCSStorage: a Google Cloud Storage bucket (gs://bucket/prefix)

To add a backend (S3, Azure, ...), subclass Storage, implement its abstract methods and
add it to BACKENDS.
"""

from __future__ import annotations

from pathlib import Path

from artifactum.exceptions import StorageError
from artifactum.storage.base import Storage
from artifactum.storage.gcs import GCSStorage
from artifactum.storage.local import LocalStorage

__all__ = ["BACKENDS", "GCSStorage", "LocalStorage", "Storage", "normalise_location", "storage_for", "where"]

# URL scheme → backend
BACKENDS: dict[str, type[Storage]] = {cls.scheme: cls for cls in (LocalStorage, GCSStorage)}


def normalise_location(location: str) -> str:
    """Turn what a user types into a storage URL.

    ``gs://...`` and ``file://...`` are kept. A path (``/groups/lab/atfm``, ``~/atfm``,
    ``./atfm``) becomes an absolute ``file://`` URL. A bare name (``my-bucket/atfm``) is a
    GCS bucket, as it was before local storage existed.
    """
    location = location.strip()
    if not location:
        raise StorageError("No storage location is set. Run `atfm init` to choose one.")
    if "://" in location:
        return location.rstrip("/")
    if location.startswith(("/", "~", ".")) or Path(location).is_absolute():
        return LocalStorage.url_of(Path(location).expanduser().resolve())
    return f"gs://{location.rstrip('/')}"


def storage_for(location: str) -> Storage:
    """The backend for a storage location or for one stored file's URL."""
    url = normalise_location(location)
    scheme = url.split("://", 1)[0]
    if scheme not in BACKENDS:
        known = ", ".join(f"{s}://" for s in BACKENDS)
        raise StorageError(f"Unsupported storage location {url!r}; use a directory or one of {known}")
    return BACKENDS[scheme](url)


def where(url: str) -> str:
    """A stored file's location as a person would type it: a path, for files in a directory."""
    try:
        return storage_for(url).display(url)
    except StorageError:
        return url
