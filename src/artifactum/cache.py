from __future__ import annotations

import shutil
from pathlib import Path

from artifactum.config import Config


class Cache:
    def __init__(self, config: Config):
        self._root = config.cache_path
        self._limit_bytes = int(config.cache_limit_gb * 1024**3)
        self._root.mkdir(parents=True, exist_ok=True)

    def _entry(self, content_hash: str) -> Path:
        return self._root / content_hash

    def get(self, content_hash: str) -> Path | None:
        p = self._entry(content_hash)
        if p.exists():
            p.touch()  # update atime for LRU tracking
            return p
        return None

    def put(self, content_hash: str, src: Path) -> Path:
        dest = self._entry(content_hash)
        if not dest.exists():
            shutil.copy2(src, dest)
            self._evict_if_needed()
        return dest

    def _evict_if_needed(self) -> None:
        entries = list(self._root.iterdir())
        total = sum(e.stat().st_size for e in entries)
        if total <= self._limit_bytes:
            return
        # Sort by atime ascending (oldest first)
        entries.sort(key=lambda e: e.stat().st_atime)
        for e in entries:
            if total <= self._limit_bytes:
                break
            total -= e.stat().st_size
            e.unlink()
