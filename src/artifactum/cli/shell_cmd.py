"""Shell commands: use Artifactum from bash, R, Nextflow, Snakemake or any other tool.

stdout carries only the result (a path or an ID) so commands compose, or with --json one
JSON object, for tools that would rather parse than split strings (R's jsonlite, jq, ...):

    eval "$(atfm run start 'align reads')"     # group what follows into one run
    bwa mem "$(atfm get GRCH38RF)" "$(atfm get FQ7R1A2B)" > aligned.sam
    atfm publish aligned.bam -d "Reads aligned with BWA-MEM" --code align.sh
    # → parents GRCH38RF and FQ7R1A2B, recorded automatically
    eval "$(atfm run end)"
"""
from __future__ import annotations

import getpass
import json
import os
import platform
import shutil
import socket
from pathlib import Path
from typing import NoReturn

from rich.console import Console

from artifactum.exceptions import ArtifactumError

err = Console(stderr=True)


def fail(message: str) -> NoReturn:
    """Print an error on stderr and exit with status 1."""
    err.print(f"[red]{message}[/red]")
    raise SystemExit(1)


def emit_json(obj: object) -> None:
    """One JSON object on a single line of stdout; messages stay on stderr."""
    print(json.dumps(obj, default=str))


def get(artifact_id: str, to: Path | None = None, as_json: bool = False) -> None:
    """Fetch an artifact and print its local path. Inside a run, it's recorded as an input."""
    import artifactum

    try:
        path = Path(artifactum.artifact(artifact_id))
    except ArtifactumError as e:
        fail(str(e) or f"Could not fetch {artifact_id}")
    if to is not None:
        target = to / path.name if to.is_dir() else to
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        path = target
    if as_json:
        emit_json({"id": artifact_id, "path": str(path)})
    else:
        print(path)


def publish(
    file: Path,
    description: str | None = None,
    tag: list[str] | None = None,
    parent: list[str] | None = None,
    no_parents: bool = False,
    name: str | None = None,
    docs: Path | None = None,
    code: Path | None = None,
    as_json: bool = False,
) -> None:
    """Publish a file and print its ID. Inside a run, its inputs become the parents."""
    from artifactum import _publish
    from artifactum.provenance import git_info
    from artifactum.tracking import current_scope

    scope = current_scope()
    if no_parents:
        parents: list[str] | None = []
    elif parent:
        parents = list(parent)
    else:
        parents = None  # the run's inputs (none outside a run)
    recorded = list(parents) if parents is not None else list(scope.inputs)

    where = code.resolve() if code else Path.cwd()
    try:
        user = getpass.getuser()
    except Exception:
        user = None
    environment = {
        "entrypoint": str(code.resolve()) if code else (scope.name or "shell"),
        "argv": [],
        **git_info(where),
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "os_user": user,
    }
    try:
        artifact_id = _publish(
            file, parents=parents, description=description, tags=list(tag or []) or None,
            docs=docs, name=name, environment=environment, code_path=code.resolve() if code else None,
        )
    except ArtifactumError as e:
        fail(str(e) or "Publish failed")
    if scope.state_path is None and parents is None:
        err.print("[dim]No parents recorded: pass --parent, or start a run with `eval \"$(atfm run start)\"`.[/dim]")
    if as_json:
        emit_json({"id": artifact_id, "file": str(file.resolve()), "parents": recorded, "run_id": scope.run_id if scope.state_path else None})
    else:
        print(artifact_id)


def run_start(name: str | None = None) -> None:
    """Start a run. Use as: eval "$(atfm run start 'align reads')"."""
    from artifactum.tracking import start_shell_run

    scope = start_shell_run(name)
    print(f"export ARTIFACTUM_RUN={scope.run_id}")
    err.print(f"[dim]Run {scope.run_id[:8]} started{f' ({name})' if name else ''}. "
              "Artifacts fetched with `atfm get` now become parents of what you publish.[/dim]")


def run_end() -> None:
    """End the current run. Use as: eval "$(atfm run end)"."""
    from artifactum.tracking import runs_dir

    run_id = os.environ.get("ARTIFACTUM_RUN")
    if run_id:
        (runs_dir() / f"{run_id}.json").unlink(missing_ok=True)
    print("unset ARTIFACTUM_RUN")


def run_status(as_json: bool = False) -> None:
    """Show the current run and the inputs recorded so far."""
    from artifactum.tracking import current_scope

    scope = current_scope()
    if as_json:
        in_run = scope.state_path is not None
        emit_json({
            "run_id": scope.run_id if in_run else None,
            "name": scope.name if in_run else None,
            "started_at": scope.started_at.isoformat() if in_run else None,
            "inputs": list(scope.inputs) if in_run else [],
        })
        return
    if scope.state_path is None:
        err.print('No run in progress. Start one with: eval "$(atfm run start NAME)"')
        return
    err.print(f"Run {scope.run_id}{f' ({scope.name})' if scope.name else ''}, started {scope.started_at:%Y-%m-%d %H:%M}")
    err.print(f"Inputs: {', '.join(scope.inputs) or 'none yet'}")
