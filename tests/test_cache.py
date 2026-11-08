import tempfile
from pathlib import Path

import pytest

from artifactum.cache import Cache
from artifactum.config import Config


def _config(tmp_path: Path, limit_gb: float = 1.0) -> Config:
    return Config(
        api_token="",
        server_url="",
        gcs_bucket="",
        cache_dir=str(tmp_path / "cache"),
        cache_limit_gb=limit_gb,
    )


def test_put_and_get(tmp_path: Path) -> None:
    cache = Cache(_config(tmp_path))
    src = tmp_path / "file.txt"
    src.write_bytes(b"hello")

    path = cache.put("abc123", src)
    assert path.exists()
    assert path.read_bytes() == b"hello"

    result = cache.get("abc123")
    assert result is not None
    assert result == path


def test_get_miss(tmp_path: Path) -> None:
    cache = Cache(_config(tmp_path))
    assert cache.get("notexist") is None


def test_idempotent_put(tmp_path: Path) -> None:
    cache = Cache(_config(tmp_path))
    src = tmp_path / "f.txt"
    src.write_bytes(b"data")
    p1 = cache.put("hash1", src)
    p2 = cache.put("hash1", src)
    assert p1 == p2


def test_eviction(tmp_path: Path) -> None:
    # limit to ~10 bytes — any file larger will trigger eviction
    limit_bytes = 10
    config = Config(
        api_token="",
        server_url="",
        gcs_bucket="",
        cache_dir=str(tmp_path / "cache"),
        cache_limit_gb=limit_bytes / 1024**3,
    )
    cache = Cache(config)

    f1 = tmp_path / "f1.bin"
    f1.write_bytes(b"x" * 6)
    f2 = tmp_path / "f2.bin"
    f2.write_bytes(b"y" * 6)

    cache.put("h1", f1)
    cache.put("h2", f2)

    # After eviction, total cache should be <= limit
    total = sum(e.stat().st_size for e in cache._root.iterdir())
    assert total <= limit_bytes
