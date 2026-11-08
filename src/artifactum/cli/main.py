"""Artifactum CLI entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

app = typer.Typer(name="artifactum", help="Artifactum: a registry and lineage tracker for your data files.")
console = Console()

# Shell use: atfm get / atfm publish / atfm run (see shell_cmd.py)
from artifactum.cli import shell_cmd  # noqa: E402

app.command("get")(shell_cmd.get)
app.command("publish")(shell_cmd.publish)
app.add_typer(shell_cmd.run_app, name="run")


@app.command()
def init() -> None:
    """Set up Artifactum for the first time (API token, GCS bucket, cache)."""
    from artifactum.cli.init_cmd import run_init
    run_init()


@app.command()
def browse() -> None:
    """Open the interactive TUI for artifact discovery and lineage browsing."""
    from artifactum.cli.tui import run_browse
    run_browse()


@app.command()
def log(artifact_id: str = typer.Argument(..., help="Artifact ID (e.g. XBHFAL)")) -> None:
    """Print the full upstream lineage chain for an artifact."""
    from artifactum.client import ArtifactumClient
    from artifactum.config import load_config

    config = load_config()
    client = ArtifactumClient(config)

    def _build_tree(aid: str, tree: Tree | None = None, visited: set[str] | None = None) -> Tree:
        if visited is None:
            visited = set()
        if aid in visited:
            return tree  # type: ignore[return-value]
        visited.add(aid)

        try:
            meta = client.get_artifact(aid)
        except Exception as e:
            label = f"[red]{aid} (error: {e})[/red]"
            if tree is None:
                return Tree(label)
            tree.add(label)
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


@app.command()
def describe(artifact_id: str = typer.Argument(..., help="Artifact ID (e.g. XBHFAL)")) -> None:
    """Print detailed metadata for an artifact."""
    from artifactum.client import ArtifactumClient
    from artifactum.config import load_config

    config = load_config()
    client = ArtifactumClient(config)

    meta = client.get_artifact(artifact_id)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold")
    table.add_column("Value")

    filename = meta.gcs_url.rsplit("/", 1)[-1] if meta.gcs_url else artifact_id

    table.add_row("ID", meta.id)
    table.add_row("File", filename)
    table.add_row("Description", meta.description or "—")
    table.add_row("Tags", ", ".join(meta.tags) if meta.tags else "—")
    table.add_row("Size", _fmt_bytes(meta.size_bytes))
    table.add_row("Type", meta.content_type or "—")
    table.add_row("Published", meta.created_at or "—")
    table.add_row("GCS URL", meta.gcs_url)
    table.add_row("Hash", meta.hash)

    run = client.get_run(artifact_id)
    if run:
        table.add_row("", "")
        table.add_row("Produced by", run.get("name") or run.get("entrypoint") or "—")
        if run.get("git_commit"):
            dirty = " (uncommitted changes)" if run.get("git_dirty") else ""
            table.add_row("Git", f"{run.get('git_path') or ''} @ {run['git_commit'][:10]} on {run.get('git_branch')}{dirty}")
        if run.get("argv"):
            table.add_row("Args", " ".join(run["argv"]))
        table.add_row("Environment", f"Python {run.get('python_version')} on {run.get('hostname')}")
        if run.get("code_url"):
            table.add_row("Code", f"{run['code_url']}  (artifactum code {artifact_id})")

    console.print(table)


@app.command()
def code(artifact_id: str = typer.Argument(..., help="Artifact ID (e.g. XBHFAL)")) -> None:
    """Print the code snapshot captured when an artifact was published."""
    import tempfile
    from pathlib import Path

    from rich.syntax import Syntax

    from artifactum.client import ArtifactumClient
    from artifactum.config import load_config
    from artifactum.gcs import download

    client = ArtifactumClient(load_config())
    run = client.get_run(artifact_id)
    if not run or not run.get("code_url"):
        console.print(f"[yellow]No code snapshot was recorded for {artifact_id}.[/yellow]")
        raise typer.Exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "code.py"
        download(run["code_url"], local)
        console.print(Syntax(local.read_text(), "python", line_numbers=True))


@app.command()
def export(
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Where to save the zip (default: artifactum-export-<date>.zip)"),
) -> None:
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


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n //= 1024
    return f"{n:.0f} PB"


if __name__ == "__main__":
    app()
