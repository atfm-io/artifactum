from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from artifactum.exceptions import StorageError
from artifactum.storage.base import Storage


class LocalStorage(Storage):
    """A directory: a shared one on a lab server or cluster, or just one on this machine.

    Everyone on the team must see it at the same path, since the registry records the
    absolute path of each file.
    """

    scheme = "file"

    @staticmethod
    def url_of(path: Path) -> str:
        # Not percent-encoded, like gs:// URLs, so file names read the same everywhere
        return f"file://{path.as_posix()}"

    @staticmethod
    def path_of(url: str) -> Path:
        return Path(url.removeprefix("file://"))

    def display(self, url: str) -> str:
        return str(self.path_of(url))

    def check(self) -> None:
        root = self.path_of(self.root)
        if not root.is_dir():
            raise StorageError(
                f"The storage directory {root} doesn't exist. Create it (or mount the shared drive) and try again."
            )
        if not os.access(root, os.W_OK):
            raise StorageError(f"You can't write to the storage directory {root}.")

    def upload(self, local: Path, url: str) -> None:
        dest = self.path_of(url)
        if dest.exists():  # content-addressed: the same content is already there
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Copy beside the destination, then rename, so readers never see a half-written file
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".upload-")
        os.close(fd)
        try:
            shutil.copyfile(local, tmp)
            os.replace(tmp, dest)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def download(self, url: str, local: Path) -> None:
        source = self.path_of(url)
        if not source.is_file():
            raise StorageError(f"{source} isn't there. Is the shared directory mounted on this machine?")
        local.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, local)
