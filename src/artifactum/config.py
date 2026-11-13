from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path

from artifactum.exceptions import ConfigError

CONFIG_DIR = Path.home() / ".artifactum"
_CONFIG_PATH = CONFIG_DIR / "config.toml"

DEFAULT_SERVER_URL = "https://atfm.io"
DEFAULT_CACHE_DIR = str(CONFIG_DIR / "cache")


@dataclass
class Config:
    api_token: str = ""
    server_url: str = DEFAULT_SERVER_URL
    # Where files are stored: a directory (usually shared) or gs://bucket/prefix
    storage: str = ""
    cache_dir: str = field(default_factory=lambda: DEFAULT_CACHE_DIR)
    cache_limit_gb: float = 2.0
    # Upload a snapshot of the running script/notebook to the bucket on publish
    capture_code: bool = True
    # Send the machine's hostname, OS user name, platform and command-line arguments with
    # each run. Turn off to keep them out of the registry; git and package details still go.
    capture_machine: bool = True

    @property
    def cache_path(self) -> Path:
        return Path(self.cache_dir).expanduser()


# Paths are looked up when called, not bound as defaults at import, so tests can redirect them


def load_config(path: Path | None = None) -> Config:
    path = path or _CONFIG_PATH
    if not path.exists():
        raise ConfigError(f"No config found at {path}. Run `atfm init` to set up.")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    section = data.get("default", data)
    return Config(
        api_token=section.get("api_token", ""),
        server_url=section.get("server_url", DEFAULT_SERVER_URL),
        storage=section.get("storage") or section.get("gcs_bucket", ""),  # gcs_bucket: the old name
        cache_dir=section.get("cache_dir", DEFAULT_CACHE_DIR),
        cache_limit_gb=float(section.get("cache_limit_gb", 2.0)),
        capture_code=bool(section.get("capture_code", True)),
        capture_machine=bool(section.get("capture_machine", True)),
    )


def save_config(config: Config, path: Path | None = None) -> None:
    import tomli_w  # imported lazily: only `init` writes config

    path = path or _CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "default": {
            "api_token": config.api_token,
            "server_url": config.server_url,
            "storage": config.storage,
            "cache_dir": config.cache_dir,
            "cache_limit_gb": config.cache_limit_gb,
            "capture_code": config.capture_code,
            "capture_machine": config.capture_machine,
        }
    }
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
