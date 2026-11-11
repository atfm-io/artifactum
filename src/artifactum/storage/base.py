from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar


class Storage(ABC):
    """A place artifact files are kept, rooted at one location: a bucket prefix or a directory.

    Concrete here, the same for every backend:
      - the layout, ``<root>/<hash[:2]>/<hash>/<filename>``: content-addressed, so a file is
        never overwritten by a different one and uploading the same file twice is harmless
      - how a stored file's location is shown to a person (``display``; a backend may override)

    Abstract, what each backend implements:
      - ``check``: can files be written to the root right now?
      - ``upload`` / ``download``: move one file to or from one of the backend's URLs

    An instance made from any of a backend's URLs can download any other of its URLs, so
    the reader of a file needn't know the root it was published under.
    """

    #: The URL scheme this backend handles, e.g. "gs"
    scheme: ClassVar[str]

    def __init__(self, root: str) -> None:
        self.root = root.rstrip("/")

    # ── The same for every backend ──────────────────────────────────────────────────

    def url_for(self, content_hash: str, filename: str) -> str:
        """Where a file with this content and name is stored."""
        return f"{self.root}/{content_hash[:2]}/{content_hash}/{filename}"

    def display(self, url: str) -> str:
        """How to show a stored file's location to a person."""
        return url

    # ── What each backend implements ────────────────────────────────────────────────

    @abstractmethod
    def check(self) -> None:
        """Raise StorageError if files can't be stored under the root. Called before a
        publish is registered, so a misconfigured location doesn't leave a record with no file."""

    @abstractmethod
    def upload(self, local: Path, url: str) -> None:
        """Copy a local file to ``url``."""

    @abstractmethod
    def download(self, url: str, local: Path) -> None:
        """Copy the file at ``url`` to ``local``. Raise StorageError if it isn't there."""
