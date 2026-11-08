"""Artifactum: a registry and lineage tracker for the files data teams produce."""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import tempfile
from pathlib import Path
from typing import Any

from artifactum.client import ArtifactMeta
from artifactum.exceptions import ArtifactNotFoundError, PlanLimitError
from artifactum.tracking import current_scope, record_input, step

__all__ = ["artifact", "publish", "search", "step", "PlanLimitError"]

log = logging.getLogger("artifactum")

# Code snapshots already uploaded by this process (content-addressed, so one upload is enough)
_uploaded_code: set[str] = set()


def _gcs_dest(gcs_bucket: str, content_hash: str, filename: str) -> str:
    bucket = gcs_bucket.rstrip("/")
    if not bucket.startswith("gs://"):
        bucket = f"gs://{bucket}"
    return f"{bucket}/{content_hash[:2]}/{content_hash}/{filename}"


def artifact(id: str) -> str:
    """Resolve an artifact ID to a local file path, fetching from GCS if needed."""
    from artifactum.cache import Cache
    from artifactum.config import load_config
    from artifactum.gcs import download
    from artifactum.hashing import sha256_file
    from artifactum.client import ArtifactumClient

    config = load_config()
    client = ArtifactumClient(config)
    meta = client.get_artifact(id)
    record_input(meta.id)
    if meta.superseded_by:
        log.warning("artifactum: %s is an older version of %s; the newest is %s", meta.id, meta.name or "this artifact", meta.superseded_by)
    elif meta.stale:
        log.warning("artifactum: %s was built from inputs that have newer versions since", meta.id)

    cache = Cache(config)
    cached = cache.get(meta.hash)
    if cached:
        return str(cached)

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        download(meta.gcs_url, tmp_path)
        actual_hash = sha256_file(tmp_path)
        if actual_hash != meta.hash:
            tmp_path.unlink(missing_ok=True)
            raise ArtifactNotFoundError(id)
        cached = cache.put(meta.hash, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return str(cached)


def publish(
    path: str | Path,
    *,
    parents: list[str] | None = None,
    parent: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    docs: str | Path | None = None,
    name: str | None = None,
) -> str:
    """Publish a file to the registry. Returns the canonical short ID.

    Parents default to every artifact read with ``artifact()`` in the current
    ``step()`` (or the whole process, outside a step). Pass ``parents=[...]`` to
    set them explicitly, or ``parents=[]`` to record none.

    ``docs`` is markdown documentation shown on the artifact's page: either the
    text itself or a path to a markdown file (e.g. a README next to your code).

    ``name`` says what this is a version of: publishing again under the same name
    records a new version, and anything built from the old one is flagged stale. It
    defaults to the file name, so give one when file names are generic (``data.csv``).
    """
    return _publish(path, parents=parents, parent=parent, description=description, tags=tags, docs=docs, name=name)


def _publish(
    path: str | Path,
    *,
    parents: list[str] | None = None,
    parent: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    docs: str | Path | None = None,
    name: str | None = None,
    environment: dict[str, Any] | None = None,
    code_path: Path | None = None,
) -> str:
    """publish(), plus the CLI's way to describe a shell run: ``environment`` replaces the
    captured Python environment and ``code_path`` is snapshotted instead of the running script."""
    from artifactum.cache import Cache
    from artifactum.config import load_config
    from artifactum.gcs import upload
    from artifactum.hashing import sha256_file
    from artifactum.client import ArtifactumClient

    config = load_config()
    client = ArtifactumClient(config)
    scope = current_scope()

    if parents is None and parent is None:
        parent_ids = list(scope.inputs)
    else:
        parent_ids = list(dict.fromkeys([*([parent] if parent else []), *(parents or [])]))

    local = Path(path).expanduser().resolve()
    content_hash = sha256_file(local)
    size_bytes = local.stat().st_size
    content_type, _ = mimetypes.guess_type(local.name)
    gcs_url = _gcs_dest(config.gcs_bucket, content_hash, local.name)

    docs_text = _read_docs(docs)

    # The first publish in a scope sends the full run record; later ones just reference it.
    run = None if scope.run_registered else _capture_run(scope, config, environment, code_path)

    artifact_id = client.register_artifact(
        hash=content_hash,
        gcs_url=gcs_url,
        size_bytes=size_bytes,
        content_type=content_type,
        parent_ids=parent_ids,
        description=description,
        tags=tags,
        run_id=scope.run_id,
        run=run,
        docs=docs_text,
        name=name,
    )
    scope.mark_registered()

    upload(local, gcs_url)
    return artifact_id


def _read_docs(docs: str | Path | None) -> str | None:
    if docs is None:
        return None
    if isinstance(docs, Path):
        return docs.expanduser().read_text()
    candidate = Path(docs).expanduser() if "\n" not in docs and len(docs) < 1024 else None
    if candidate is not None and candidate.suffix.lower() in (".md", ".markdown", ".txt") and candidate.is_file():
        return candidate.read_text()
    return docs


def _capture_run(
    scope: Any, config: Any, environment: dict[str, Any] | None = None, code_path: Path | None = None
) -> dict[str, Any]:
    """Describe the code and environment behind this scope. Never raises."""
    from artifactum.gcs import upload
    from artifactum.provenance import MACHINE_FIELDS, CodeSnapshot, capture_environment, code_snapshot

    run: dict[str, Any] = {"name": scope.name, "started_at": scope.started_at.isoformat()}
    try:
        machine = getattr(config, "capture_machine", True)
        env = dict(environment) if environment is not None else capture_environment(machine=machine)
        if not machine:  # the shell commands pass their own environment
            for field in MACHINE_FIELDS:
                env.pop(field, None)
        run.update(env)
    except Exception as e:  # provenance is best-effort; never block a publish on it
        log.warning("artifactum: could not capture run environment: %s", e)

    if not config.capture_code:
        return run
    try:
        snapshot = CodeSnapshot(code_path.name, code_path.read_bytes()) if code_path else (
            None if environment is not None else code_snapshot()
        )
        if snapshot is not None:
            code_hash = hashlib.sha256(snapshot.content).hexdigest()
            code_url = _gcs_dest(config.gcs_bucket, code_hash, snapshot.filename)
            if code_url not in _uploaded_code:
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(snapshot.content)
                try:
                    upload(Path(tmp.name), code_url)
                finally:
                    Path(tmp.name).unlink(missing_ok=True)
                _uploaded_code.add(code_url)
            run["code_hash"] = code_hash
            run["code_url"] = code_url
    except Exception as e:
        log.warning("artifactum: could not upload code snapshot: %s", e)
    return run


def search(query: str, *, tags: list[str] | None = None) -> list[ArtifactMeta]:
    """Search the registry by free text and/or tags."""
    from artifactum.config import load_config
    from artifactum.client import ArtifactumClient

    config = load_config()
    client = ArtifactumClient(config)
    return client.search(query, tags=tags)
