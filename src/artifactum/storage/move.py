"""Moving files to new storage: `atfm storage move`, or `atfm storage move --team` for a team admin.

Works for any pair of backends, through the Storage interface alone: every file is
downloaded from the old location, checked against its recorded hash and uploaded to the
same place under the new root. Only once every copy has been made are the records on the
server repointed, so a move that fails part way changes nothing and can just be rerun.
The old copies are left where they were.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from artifactum.client import ArtifactumClient
from artifactum.exceptions import StorageError
from artifactum.hashing import sha256_file
from artifactum.storage import storage_for


@dataclass
class Moved:
    artifacts: int
    code: int
    old: str
    new: str


def move_files(
    client: ArtifactumClient,
    old_location: str,
    new_location: str,
    on_file: Callable[[str], None] | None = None,
    team: bool = False,
) -> Moved:
    old, new = storage_for(old_location), storage_for(new_location)
    if old.root == new.root:
        raise StorageError(f"Your files are already in {new.display(new.root)}.")
    new.check()

    listing = client.files_under(old.root, team=team)
    files = [(a["url"], a["hash"]) for a in listing["artifacts"]] + [(c["url"], c["hash"]) for c in listing["code"]]
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "file"
        for url, content_hash in files:
            old.download(url, local)
            if sha256_file(local) != content_hash:
                raise StorageError(f"{old.display(url)} has changed since it was published, so nothing was moved.")
            new.upload(local, new.root + url.removeprefix(old.root))
            local.unlink()
            if on_file:
                on_file(url)

    counts = client.move_storage(old.root, new.root, team=team)
    return Moved(counts["artifacts"], counts["code"], old.display(old.root), new.display(new.root))
