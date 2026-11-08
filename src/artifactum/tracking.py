"""Automatic lineage: remember which artifacts were read so publish() can infer parents.

Every ``artifact(id)`` call records ``id`` in the current *scope*. ``publish()``
without explicit parents uses the scope's inputs as parents. By default there is
one process-wide scope; ``step()`` opens a narrower one so that, in a notebook or
a multi-stage script, only the reads inside that step count.

Each scope is also one *run*: every publish in it shares a run ID, so the server
can group the outputs of a step together with the code that produced them.

A *shell run* (``eval "$(atfm run start NAME)"``) extends one run across processes: it
sets ARTIFACTUM_RUN, and every process started from that shell (``atfm get``,
``atfm publish``, Python scripts) shares the run and its recorded inputs through a small
state file, so lineage works across shell pipelines, Nextflow or Snakemake steps.
"""

from __future__ import annotations

import functools
import json
import os
import threading
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class Scope:
    name: str | None = None
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    inputs: list[str] = field(default_factory=list)
    # Set once the run (and its code snapshot) has been sent to the server
    run_registered: bool = False
    # Shell runs only: where the run's state is shared with other processes
    state_path: Path | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, artifact_id: str) -> None:
        with self._lock:
            if self.state_path:
                self._reload()
            if artifact_id not in self.inputs:
                self.inputs.append(artifact_id)
            self.save()

    def mark_registered(self) -> None:
        with self._lock:
            if self.state_path:
                self._reload()
            self.run_registered = True
            self.save()

    # ── Shell-run state, shared between processes ────────────────────────────
    def _reload(self) -> None:
        try:
            data = json.loads(self.state_path.read_text())  # type: ignore[union-attr]
        except (OSError, ValueError):
            return
        self.inputs = list(dict.fromkeys([*data.get("inputs", []), *self.inputs]))
        self.run_registered = self.run_registered or bool(data.get("registered"))

    def save(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "name": self.name,
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "inputs": self.inputs,
            "registered": self.run_registered,
        }))
        os.replace(tmp, self.state_path)


def runs_dir() -> Path:
    from artifactum.config import CONFIG_DIR

    return CONFIG_DIR / "runs"


def start_shell_run(name: str | None) -> Scope:
    """Create a shell run's shared state; the caller exports ARTIFACTUM_RUN=<run_id>."""
    scope = Scope(name=name)
    scope.state_path = runs_dir() / f"{scope.run_id}.json"
    scope.save()
    return scope


def load_shell_run(run_id: str) -> Scope | None:
    path = runs_dir() / f"{run_id}.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return Scope(
        name=data.get("name"),
        run_id=data.get("run_id", run_id),
        started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else datetime.now(timezone.utc),
        inputs=list(data.get("inputs", [])),
        run_registered=bool(data.get("registered")),
        state_path=path,
    )


def _initial_scope() -> Scope:
    run_id = os.environ.get("ARTIFACTUM_RUN")
    return (load_shell_run(run_id) if run_id else None) or Scope()


_process_scope = _initial_scope()
_current: ContextVar[Scope | None] = ContextVar("artifactum_scope", default=None)


def current_scope() -> Scope:
    return _current.get() or _process_scope


def record_input(artifact_id: str) -> None:
    current_scope().record(artifact_id)


def reset() -> None:
    """Forget all reads in the process-wide scope and start a new run (or rejoin the shell run)."""
    global _process_scope
    _process_scope = _initial_scope()


class step:
    """Scope lineage tracking to a block of code or a function.

    Only artifacts read inside the step become parents of what it publishes::

        with atfm.step("join users"):
            events = pd.read_parquet(artifact("CLNEVT01"))
            users = pd.read_parquet(artifact("RAWUSR01"))
            publish("joined.parquet")          # parents: CLNEVT01, RAWUSR01

    Also works as a decorator; each call is a separate step.
    """

    def __init__(self, name: str | None = None):
        self.name = name
        self._tokens: list[Any] = []

    def __enter__(self) -> Scope:
        scope = Scope(name=self.name)
        self._tokens.append(_current.set(scope))
        return scope

    def __exit__(self, *exc: object) -> None:
        _current.reset(self._tokens.pop())

    def __call__(self, fn: F) -> F:
        name = self.name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with step(name):
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]
