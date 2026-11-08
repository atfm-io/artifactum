from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from artifactum.config import _CONFIG_PATH, Config, load_config, save_config
from artifactum.exceptions import ConfigError

console = Console()


def run_init() -> None:
    """Interactive wizard to configure Artifactum for the first time."""
    console.print("\n[bold cyan]Artifactum setup[/bold cyan]\n")
    console.print(f"This will create [bold]{_CONFIG_PATH}[/bold].\n")

    # Offer existing values (including a config from before the rename) as defaults
    try:
        current = load_config()
    except ConfigError:
        current = Config()

    server_url = Prompt.ask("Server URL", default=current.server_url)
    api_token = Prompt.ask(f"API token (from {server_url.rstrip('/')}/settings)", password=True) or current.api_token
    gcs_bucket = Prompt.ask("GCS bucket (e.g. gs://my-team-bucket/artifactum)", default=current.gcs_bucket or None)
    cache_dir = Prompt.ask("Local cache directory", default=current.cache_dir)
    cache_limit_gb_str = Prompt.ask("Cache size limit (GB)", default=f"{current.cache_limit_gb:g}")

    try:
        cache_limit_gb = float(cache_limit_gb_str)
    except ValueError:
        cache_limit_gb = 2.0

    config = Config(
        api_token=api_token,
        server_url=server_url,
        gcs_bucket=gcs_bucket or "",
        cache_dir=cache_dir,
        cache_limit_gb=cache_limit_gb,
        capture_code=current.capture_code,
        capture_machine=current.capture_machine,
    )
    save_config(config)

    cache_path = Path(cache_dir).expanduser()
    cache_path.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[green]Config saved to {_CONFIG_PATH}[/green]")
    console.print(f"[green]Cache directory ready at {cache_path}[/green]\n")
