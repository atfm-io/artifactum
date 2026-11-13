from __future__ import annotations

from dataclasses import replace

from rich.console import Console
from rich.prompt import Prompt

from artifactum.config import _CONFIG_PATH, DEFAULT_SERVER_URL, Config, load_config, save_config
from artifactum.exceptions import ArtifactumError, ConfigError
from artifactum.storage import LocalStorage, normalise_location, storage_for

console = Console()


def run_init(token: str | None = None, storage: str | None = None, server: str | None = None) -> None:
    """Set up ~/.artifactum/config.toml.

    With ``token`` and ``storage`` given (``atfm init --token ... --storage ...``, the line
    the web app's getting-started steps show), nothing is asked: everything else keeps its
    current value or default. Otherwise a short wizard asks for whatever wasn't given.
    """
    # Offer existing values (including a config from before the rename) as defaults
    try:
        current = load_config()
    except ConfigError:
        current = Config()
    # Always atfm.io unless --server says otherwise (a team's own server, or local development),
    # so a URL left over from an earlier setup doesn't stick
    current = replace(current, server_url=server or DEFAULT_SERVER_URL)

    if token and storage:
        config = replace(current, api_token=token, storage=normalise_location(storage))
    else:
        config = _ask(current, token, storage)

    save_config(config)
    cache_path = config.cache_path
    cache_path.mkdir(parents=True, exist_ok=True)

    console.print(f"[green]✓[/green] Config saved to {_CONFIG_PATH}")
    console.print(f"[green]✓[/green] Cache at {cache_path}")
    if config.storage:
        _ready_storage(config.storage)


def _ask(current: Config, token: str | None, storage: str | None) -> Config:
    console.print("\n[bold cyan]Artifactum setup[/bold cyan]\n")
    console.print(f"This will create [bold]{_CONFIG_PATH}[/bold].\n")

    server_url = current.server_url
    api_token = token or (
        Prompt.ask(f"API token (from {server_url.rstrip('/')}/settings)", password=True) or current.api_token
    )
    if not storage:
        console.print(
            "\nFiles stay in storage you control: a directory (to try it on your own, ~/atfm-files; for a team, a"
            " shared one everyone reaches at the same path, like /groups/lab/atfm), or a Google Cloud Storage"
            " bucket (gs://my-team-bucket/atfm). You can move later with `atfm storage move`."
        )
        storage = Prompt.ask("Storage location", default=current.storage or "~/atfm-files")
    cache_dir = Prompt.ask("Local cache directory", default=current.cache_dir)
    cache_limit_gb_str = Prompt.ask("Cache size limit (GB)", default=f"{current.cache_limit_gb:g}")
    try:
        cache_limit_gb = float(cache_limit_gb_str)
    except ValueError:
        cache_limit_gb = 2.0
    console.print()

    return replace(
        current,
        api_token=api_token,
        server_url=server_url,
        storage=normalise_location(storage) if storage else "",
        cache_dir=cache_dir,
        cache_limit_gb=cache_limit_gb,
    )


def _ready_storage(location: str) -> None:
    """Check the storage works. A directory that doesn't exist yet is created: naming it in
    init is a clear enough request, unlike a publish to a drive that isn't mounted."""
    backend = storage_for(location)
    if isinstance(backend, LocalStorage):
        path = backend.path_of(backend.root)
        if not path.exists():
            try:
                path.mkdir(parents=True)
                console.print(f"[green]✓[/green] Created {path} for your files")
            except OSError as e:
                console.print(f"[yellow]Couldn't create {path}: {e.strerror}[/yellow]")
                return
    try:
        backend.check()
        console.print(f"[green]✓[/green] Files will be stored in {backend.display(backend.root)}")
    except ArtifactumError as e:
        console.print(f"[yellow]{e}[/yellow]")
