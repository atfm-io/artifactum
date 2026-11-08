from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from artifactum.exceptions import ConfigError

CONFIG_DIR = Path.home() / ".artifactum"
_CONFIG_PATH = CONFIG_DIR / "config.toml"
# Read when the new config doesn't exist yet, so setups from before the rename keep working
_LEGACY_CONFIG_PATH = Path.home() / ".dregs" / "config.toml"

DEFAULT_SERVER_URL = "https://dregs.chrisbcole.me"
DEFAULT_CACHE_DIR = str(CONFIG_DIR / "cache")


@dataclass
class Config:
    api_token: str = ""
    server_url: str = DEFAULT_SERVER_URL
    gcs_bucket: str = ""
    cache_dir: str = DEFAULT_CACHE_DIR
    cache_limit_gb: float = 2.0
    # Upload a snapshot of the running script/notebook to the bucket on publish
    capture_code: bool = True
    # Send the machine's hostname, OS user name, platform and command-line arguments with
    # each run. Turn off to keep them out of the registry; git and package details still go.
    capture_machine: bool = True

    @property
    def cache_path(self) -> Path:
        return Path(self.cache_dir).expanduser()


def load_config(path: Path = _CONFIG_PATH) -> Config:
    if not path.exists() and path == _CONFIG_PATH and _LEGACY_CONFIG_PATH.exists():
        path = _LEGACY_CONFIG_PATH
    if not path.exists():
        raise ConfigError(f"No config found at {path}. Run `artifactum init` to set up.")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    section = data.get("default", data)
    return Config(
        api_token=section.get("api_token", ""),
        server_url=section.get("server_url", DEFAULT_SERVER_URL),
        gcs_bucket=section.get("gcs_bucket", ""),
        cache_dir=section.get("cache_dir", DEFAULT_CACHE_DIR),
        cache_limit_gb=float(section.get("cache_limit_gb", 2.0)),
        capture_code=bool(section.get("capture_code", True)),
        capture_machine=bool(section.get("capture_machine", True)),
    )


def save_config(config: Config, path: Path = _CONFIG_PATH) -> None:
    import tomli_w  # imported lazily: only `init` writes config

    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "default": {
            "api_token": config.api_token,
            "server_url": config.server_url,
            "gcs_bucket": config.gcs_bucket,
            "cache_dir": config.cache_dir,
            "cache_limit_gb": config.cache_limit_gb,
            "capture_code": config.capture_code,
            "capture_machine": config.capture_machine,
        }
    }
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
