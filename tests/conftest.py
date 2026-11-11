from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from tests.fakes import SERVER_URL, TOKEN, FakeBucket, FakeServer


@dataclass
class Registry:
    server: FakeServer
    bucket: FakeBucket
    config_path: Path
    tmp_path: Path

    def configure(self, **changes) -> None:
        """Rewrite the user's config file, e.g. to act as another machine with its own cache."""
        from artifactum.config import load_config, save_config

        config = load_config(self.config_path)
        for key, value in changes.items():
            setattr(config, key, value)
        save_config(config, self.config_path)


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Registry:
    """A configured user talking to a fake server and bucket, with a fresh process state."""
    import artifactum
    from artifactum import config as config_mod
    from artifactum import gcs, tracking

    server, bucket = FakeServer(), FakeBucket(tmp_path / "gcs")

    real_client = httpx.Client
    transport = httpx.MockTransport(server.handle)
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setattr(gcs.storage, "Client", bucket)

    config_path = tmp_path / "home" / ".artifactum" / "config.toml"
    config_mod.save_config(
        config_mod.Config(
            api_token=TOKEN,
            server_url=SERVER_URL,
            gcs_bucket="gs://team-bucket/atfm",
            cache_dir=str(tmp_path / "cache"),
        ),
        config_path,
    )
    real_load = config_mod.load_config
    monkeypatch.setattr(config_mod, "load_config", lambda path=config_path: real_load(path))

    monkeypatch.setattr(tracking, "runs_dir", lambda: tmp_path / "runs")
    monkeypatch.delenv("ARTIFACTUM_RUN", raising=False)
    monkeypatch.setattr(artifactum, "_uploaded_code", set())
    tracking.reset()
    return Registry(server, bucket, config_path, tmp_path)
