"""Artifactum CLI entry point: the `artifactum` and `atfm` commands, parsed with jsonargparse."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from jsonargparse import ArgumentParser
from jsonargparse import Path as ParsedPath
from jsonargparse.typing import Path_fr
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

# Shell use: atfm get / atfm publish / atfm run (see shell_cmd.py)
from artifactum.cli import shell_cmd
from artifactum.exceptions import ArtifactumError
from artifactum.storage import where

console = Console()


def init(token: str | None = None, storage: str | None = None, server: str | None = None) -> None:
    """Set up Artifactum: your API token, where files are stored, and the local cache."""
    from artifactum.cli.init_cmd import run_init

    run_init(token=token, storage=storage, server=server)


def storage_move(location: str) -> None:
    """Copy the files you've published to new storage, and point their records there."""
    from dataclasses import replace

    from artifactum.client import ArtifactumClient
    from artifactum.config import load_config, save_config
    from artifactum.storage import normalise_location
    from artifactum.storage.move import move_files

    config = load_config()
    with console.status("Copying your files…") as status:
        moved = move_files(
            ArtifactumClient(config),
            config.storage,
            location,
            on_file=lambda url: status.update(f"Copied {url.rsplit('/', 1)[-1]}"),
        )
    save_config(replace(config, storage=normalise_location(location)))
    console.print(
        f"[green]✓[/green] Moved {moved.artifacts} artifact{'s' * (moved.artifacts != 1)} and {moved.code} code"
        f" snapshot{'s' * (moved.code != 1)} to {moved.new}, and new files will go there too."
    )
    console.print(f"  The old copies in {moved.old} are untouched; delete them once you're happy.")


def browse() -> None:
    """Preview: browse your 20 most recent artifacts in the terminal (work in progress)."""
    from artifactum.cli.tui import run_browse

    run_browse()


def log(artifact_id: str, as_json: bool = False) -> None:
    """Print the full upstream lineage chain for an artifact."""
    from artifactum.client import ArtifactumClient
    from artifactum.config import load_config

    config = load_config()
    client = ArtifactumClient(config)

    if as_json:
        shell_cmd.emit_json(_lineage_json(client, artifact_id, set()))
        return

    def _build_tree(aid: str, tree: Tree | None = None, visited: set[str] | None = None) -> Tree:
        if visited is None:
            visited = set()
        if aid in visited:
            return tree  # type: ignore[return-value]
        visited.add(aid)

        try:
            meta = client.get_artifact(aid)
        except Exception as e:
            if tree is None:  # the artifact asked for: report it as an error
                raise
            tree.add(f"[red]{aid} (error: {e})[/red]")  # a parent: show what could be read
            return tree

        filename = meta.gcs_url.rsplit("/", 1)[-1] if meta.gcs_url else aid
        date_str = (meta.created_at or "")[:10]
        desc_str = f'"{meta.description}"' if meta.description else ""
        label = f"[bold cyan]{aid}[/bold cyan]  {filename:<30}  {date_str}  {desc_str}"

        node = Tree(label) if tree is None else tree.add(label)

        lineage = client.get_lineage(aid)
        for parent in lineage.get("parents", []):
            _build_tree(parent["id"], node, visited)

        return node if tree is None else tree

    root = _build_tree(artifact_id)
    console.print(root)


def describe(artifact_id: str, as_json: bool = False) -> None:
    """Print detailed metadata for an artifact."""
    from dataclasses import asdict

    from artifactum.client import ArtifactumClient
    from artifactum.config import load_config

    config = load_config()
    client = ArtifactumClient(config)

    meta = client.get_artifact(artifact_id)
    if as_json:
        shell_cmd.emit_json({**asdict(meta), "run": client.get_run(artifact_id)})
        return

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold")
    table.add_column("Value", overflow="fold")  # wrap long paths rather than cut them off

    filename = meta.gcs_url.rsplit("/", 1)[-1] if meta.gcs_url else artifact_id

    table.add_row("ID", meta.id)
    table.add_row("File", filename)
    table.add_row("Description", meta.description or "—")
    table.add_row("Tags", ", ".join(meta.tags) if meta.tags else "—")
    table.add_row("Size", _fmt_bytes(meta.size_bytes))
    table.add_row("Type", meta.content_type or "—")
    table.add_row("Published", meta.created_at or "—")
    table.add_row("Stored at", where(meta.gcs_url))
    table.add_row("Hash", meta.hash)

    run = client.get_run(artifact_id)
    if run:
        table.add_row("", "")
        table.add_row("Produced by", run.get("name") or run.get("entrypoint") or "—")
        if run.get("git_commit"):
            dirty = " (uncommitted changes)" if run.get("git_dirty") else ""
            table.add_row(
                "Git", f"{run.get('git_path') or ''} @ {run['git_commit'][:10]} on {run.get('git_branch')}{dirty}"
            )
        if run.get("argv"):
            table.add_row("Args", " ".join(run["argv"]))
        machine = " on ".join(
            x for x in (run.get("python_version") and f"Python {run['python_version']}", run.get("hostname")) if x
        )
        if machine:  # shell runs have no Python version; with capture_machine off there's no hostname
            table.add_row("Environment", machine)
        if run.get("code_url"):
            table.add_row("Code", f"{where(run['code_url'])}  (atfm code {artifact_id})")

    console.print(table)


def code(artifact_id: str) -> None:
    """Print the code snapshot captured when an artifact was published."""
    import tempfile

    from rich.syntax import Syntax

    from artifactum.client import ArtifactumClient
    from artifactum.config import load_config
    from artifactum.storage import storage_for

    client = ArtifactumClient(load_config())
    run = client.get_run(artifact_id)
    if not run or not run.get("code_url"):
        console.print(f"[yellow]No code snapshot was recorded for {artifact_id}.[/yellow]")
        raise SystemExit(1)

    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "code.py"
        storage_for(run["code_url"]).download(run["code_url"], local)
        console.print(Syntax(local.read_text(), "python", line_numbers=True))


def export(output: Path | None = None) -> None:
    """Download everything in your registry: artifacts, lineage, runs, uses, edits, docs and collections."""
    from datetime import date

    from artifactum.client import ArtifactumClient
    from artifactum.config import load_config

    dest = output or Path(f"artifactum-export-{date.today():%Y-%m-%d}.zip")
    if dest.is_dir():
        dest = dest / f"artifactum-export-{date.today():%Y-%m-%d}.zip"
    with console.status("Exporting the registry…"):
        size = ArtifactumClient(load_config()).download_export(dest)
    console.print(f"[green]✓[/green] Saved {dest} ({_fmt_bytes(size)})")


def _lineage_json(client, aid: str, visited: set[str]) -> dict:
    """{id, filename, description, created_at, parents: [...]}, each artifact expanded once."""
    if aid in visited:
        return {"id": aid, "seen": True, "parents": []}
    root = not visited
    visited.add(aid)
    try:
        meta = client.get_artifact(aid)
    except Exception as e:
        if root:
            raise
        return {"id": aid, "error": str(e), "parents": []}
    parents = client.get_lineage(aid).get("parents", [])
    return {
        "id": aid,
        "filename": meta.gcs_url.rsplit("/", 1)[-1] if meta.gcs_url else None,
        "description": meta.description,
        "created_at": meta.created_at,
        "parents": [_lineage_json(client, p["id"], visited) for p in parents],
    }


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n //= 1024
    return f"{n:.0f} PB"


# ── Command line ─────────────────────────────────────────────────────────────────

ID_HELP = "Artifact ID (e.g. XBHFAL3R)"
JSON_HELP = "Print the result as one JSON object on stdout"


def _command(parent, name: str, fn: Callable) -> ArgumentParser:
    """Add a subcommand whose help is the first line of fn's docstring."""
    parser = ArgumentParser(description=fn.__doc__)
    parent.add_subcommand(name, parser, help=(fn.__doc__ or "").split("\n")[0])
    return parser


def _json(parser: ArgumentParser) -> None:
    parser.add_argument("--json", dest="as_json", action="store_true", help=JSON_HELP)


# Each command's arguments are named after its function's parameters, so the parsed
# values are passed straight through as keyword arguments.
COMMANDS: dict[str, Callable] = {
    "get": shell_cmd.get,
    "publish": shell_cmd.publish,
    "run start": shell_cmd.run_start,
    "run end": shell_cmd.run_end,
    "run status": shell_cmd.run_status,
    "init": init,
    "storage move": storage_move,
    "browse": browse,
    "log": log,
    "describe": describe,
    "code": code,
    "export": export,
}


def build_parser() -> ArgumentParser:
    from importlib.metadata import version

    parser = ArgumentParser(
        prog="atfm",
        description="Artifactum: a registry and lineage tracker for your data files.",
        version=version("artifactum"),
    )
    commands = parser.add_subcommands(dest="command")

    p = _command(commands, "get", shell_cmd.get)
    p.add_argument("artifact_id", help=ID_HELP)
    p.add_argument("-o", "--to", type=Path, help="Also copy the file here (a file or directory)")
    _json(p)

    p = _command(commands, "publish", shell_cmd.publish)
    p.add_argument("file", type=Path_fr, help="The file to publish")
    p.add_argument("-d", "--description")
    p.add_argument("-t", "--tag", action="append", help="Tag (repeatable)")
    p.add_argument("-p", "--parent", action="append", help="Parent artifact ID (repeatable). Default: the run's inputs")
    p.add_argument("--no-parents", dest="no_parents", action="store_true", help="Record no parents, even inside a run")
    p.add_argument("-n", "--name", help="What this is a version of. Without it, the file name")
    p.add_argument("--docs", type=Path_fr, help="Markdown file shown on the artifact's page")
    p.add_argument("--code", type=Path_fr, help="The script that made it, snapshotted as provenance")
    _json(p)

    run = ArgumentParser(description="Group shell commands into one run, so lineage is recorded across them.")
    commands.add_subcommand("run", run, help="Group shell commands into one run, so lineage is recorded across them.")
    actions = run.add_subcommands(dest="action")
    _command(actions, "start", shell_cmd.run_start).add_argument("name", nargs="?", help="Shown as the run's name")
    _command(actions, "end", shell_cmd.run_end)
    _json(_command(actions, "status", shell_cmd.run_status))

    p = _command(commands, "init", init)
    p.add_argument("--token", help="Your API token (from Settings on the website); skips the questions with --storage")
    p.add_argument("--storage", help="Where files are stored: a directory (e.g. ~/atfm-files) or gs://bucket/path")
    p.add_argument("--server", help="Server URL, if your team runs its own (default: https://atfm.io)")

    storage = ArgumentParser(description="Manage where your files are stored.")
    commands.add_subcommand("storage", storage, help="Manage where your files are stored.")
    moves = storage.add_subcommands(dest="action")
    _command(moves, "move", storage_move).add_argument(
        "location", help="The new location: a directory (e.g. /groups/lab/atfm) or gs://bucket/path"
    )
    _command(commands, "browse", browse)
    for name, fn in (("log", log), ("describe", describe)):
        p = _command(commands, name, fn)
        p.add_argument("artifact_id", help=ID_HELP)
        _json(p)
    _command(commands, "code", code).add_argument("artifact_id", help=ID_HELP)
    _command(commands, "export", export).add_argument(
        "-o", "--output", type=Path, help="Where to save the zip (default: artifactum-export-<date>.zip)"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    import sys

    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if argv in ([], ["run"], ["storage"]):  # a bare group: show what's in it
        parser.parse_args([*argv, "--help"])
    cfg = parser.parse_args(argv)
    name, args = cfg.command, cfg[cfg.command]
    if name in ("run", "storage"):
        name, args = f"{name} {args.action}", args[args.action]
    kwargs = args.as_dict() if args else {}
    # File arguments arrive as jsonargparse paths (checked to exist); commands take pathlib paths
    kwargs = {k: Path(v) if isinstance(v, ParsedPath) else v for k, v in kwargs.items()}
    try:
        COMMANDS[name](**kwargs)
    except ArtifactumError as e:  # unknown ID, bad token, no config, plan limit...: a message, not a traceback
        shell_cmd.fail(str(e))


if __name__ == "__main__":
    main()
