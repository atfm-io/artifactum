from pathlib import Path

import pytest

from artifactum.config import Config, load_config, save_config
from artifactum.exceptions import ConfigError


def test_round_trip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    config = Config(
        api_token="atfm_live_abc",
        server_url="https://artifactum.example.com",
        storage="gs://my-bucket/artifactum",
        cache_dir=str(tmp_path / "cache"),
        cache_limit_gb=5.0,
    )
    save_config(config, cfg_path)
    loaded = load_config(cfg_path)

    assert loaded.api_token == "atfm_live_abc"
    assert loaded.server_url == "https://artifactum.example.com"
    assert loaded.storage == "gs://my-bucket/artifactum"
    assert loaded.cache_limit_gb == 5.0


def test_load_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nonexistent.toml")


def test_cache_path_property(tmp_path: Path) -> None:
    config = Config(cache_dir=str(tmp_path / "my-cache"))
    assert config.cache_path == tmp_path / "my-cache"


def test_a_config_from_before_local_storage_keeps_its_bucket(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[default]\napi_token = "t"\ngcs_bucket = "gs://lab/atfm"\n')
    assert load_config(path).storage == "gs://lab/atfm"
