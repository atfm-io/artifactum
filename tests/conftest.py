from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from tests.fakes import SERVER_URL, TOKEN, FakeBucket, FakeServer


@dataclass
class Registry:
    server: FakeServer
    #: Where stored files end up on disk: the shared directory, or the fake bucket's files
    store_root: Path
    config_path: Path
    tmp_path: Path
    downloads: int = 0

    def stored(self, url: str) -> Path:
        """The file on disk behind a storage URL."""
        if url.startswith("file://"):
            return Path(url.removeprefix("file://"))
        return self.store_root / url.removeprefix("gs://").split("/", 1)[1]  # drop the bucket name

    def configure(self, **changes) -> None:
        """Rewrite the user's config file, e.g. to act as another machine with its own cache."""
        from artifactum.config import load_config, save_config

        config = load_config(self.config_path)
        for key, value in changes.items():
            setattr(config, key, value)
        save_config(config, self.config_path)


@pytest.fixture
def registry(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Registry:
    """A configured user talking to a fake server, with a fresh process state.

    Files are stored in a fake GCS bucket by default; parametrize with "local" to store
    them in a real directory instead (``pytest.mark.parametrize("registry", [...], indirect=True)``).
    """
    import artifactum
    from artifactum import config as config_mod
    from artifactum import tracking
    from artifactum.storage import GCSStorage, LocalStorage

    server = FakeServer()
    real_client = httpx.Client
    transport = httpx.MockTransport(server.handle)
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=transport, **kw))

    backend = getattr(request, "param", "gcs")
    if backend == "gcs":
        bucket = FakeBucket(tmp_path / "gcs")
        monkeypatch.setattr(GCSStorage, "_client", lambda self: bucket)
        location, store_root, backend_cls = "gs://team-bucket/atfm", tmp_path / "gcs" / "team-bucket", GCSStorage
    else:
        store_root = tmp_path / "shared" / "atfm"
        store_root.mkdir(parents=True)
        location, backend_cls = LocalStorage.url_of(store_root), LocalStorage

    config_path = tmp_path / "home" / ".artifactum" / "config.toml"
    config_mod.save_config(
        config_mod.Config(api_token=TOKEN, server_url=SERVER_URL, storage=location, cache_dir=str(tmp_path / "cache")),
        config_path,
    )
    real_load = config_mod.load_config
    monkeypatch.setattr(config_mod, "load_config", lambda path=config_path: real_load(path))

    monkeypatch.setattr(tracking, "runs_dir", lambda: tmp_path / "runs")
    monkeypatch.delenv("ARTIFACTUM_RUN", raising=False)
    monkeypatch.setattr(artifactum, "_uploaded_code", set())
    tracking.reset()
    reg = Registry(server, store_root, config_path, tmp_path)

    real_download = backend_cls.download

    def counted(self, url: str, local: Path) -> None:
        reg.downloads += 1
        real_download(self, url, local)

    monkeypatch.setattr(backend_cls, "download", counted)
    return reg
