import hashlib
import tempfile
from pathlib import Path

from artifactum.hashing import sha256_file


def test_sha256_matches_stdlib():
    content = b"hello artifactum " * 1000
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(content)
        tmp = Path(f.name)
    try:
        expected = hashlib.sha256(content).hexdigest()
        assert sha256_file(tmp) == expected
    finally:
        tmp.unlink()


def test_sha256_empty_file():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        tmp = Path(f.name)
    try:
        expected = hashlib.sha256(b"").hexdigest()
        assert sha256_file(tmp) == expected
    finally:
        tmp.unlink()
