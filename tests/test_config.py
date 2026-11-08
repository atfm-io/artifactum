from pathlib import Path

import pytest

from artifactum.config import Config, load_config, save_config
from artifactum.exceptions import ConfigError


def test_round_trip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    config = Config(
        api_token="atfm_live_abc",
        server_url="https://artifactum.example.com",
        gcs_bucket="gs://my-bucket/artifactum",
        cache_dir=str(tmp_path / "cache"),
        cache_limit_gb=5.0,
    )
    save_config(config, cfg_path)
    loaded = load_config(cfg_path)

    assert loaded.api_token == "atfm_live_abc"
    assert loaded.server_url == "https://artifactum.example.com"
    assert loaded.gcs_bucket == "gs://my-bucket/artifactum"
    assert loaded.cache_limit_gb == 5.0


def test_load_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nonexistent.toml")


def test_cache_path_property(tmp_path: Path) -> None:
    config = Config(cache_dir=str(tmp_path / "my-cache"))
    assert config.cache_path == tmp_path / "my-cache"


def test_falls_back_to_pre_rename_config(tmp_path, monkeypatch):
    import artifactum.config as cfg

    new, legacy = tmp_path / ".artifactum" / "config.toml", tmp_path / ".dregs" / "config.toml"
    monkeypatch.setattr(cfg, "_CONFIG_PATH", new)
    monkeypatch.setattr(cfg, "_LEGACY_CONFIG_PATH", legacy)
    save_config(Config(api_token="old-token", server_url="https://old.example.com"), legacy)

    # load_config's default argument was bound at import, so pass the patched path explicitly
    assert cfg.load_config(new).api_token == "old-token"

    save_config(Config(api_token="new-token"), new)
    assert cfg.load_config(new).api_token == "new-token"  # the new file wins once it exists


def test_old_hosted_address_is_read_as_the_new_one(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[default]\napi_token = "t"\nserver_url = "https://dregs.chrisbcole.me/"\n')
    assert load_config(path).server_url == "https://atfm.io"
    path.write_text('[default]\napi_token = "t"\nserver_url = "https://registry.acme.internal"\n')
    assert load_config(path).server_url == "https://registry.acme.internal"
