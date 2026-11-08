import hashlib
from pathlib import Path

_CHUNK = 1 << 20  # 1 MB


def sha256_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of a file, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()
