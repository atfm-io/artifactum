from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import httpx

from artifactum.config import Config
from artifactum.exceptions import ArtifactNotFoundError, ArtifactumError, AuthError, PlanLimitError


@dataclass
class ArtifactMeta:
    id: str
    hash: str
    gcs_url: str
    content_type: str | None
    size_bytes: int | None
    description: str | None
    tags: list[str] = field(default_factory=list)
    created_at: str | None = None
    owner_id: str | None = None
    name: str | None = None
    superseded_by: str | None = None
    stale: bool = False


class Registered(NamedTuple):
    id: str
    # The same content was already registered: this is its ID, and nothing about it changed
    existing: bool = False


@dataclass
class LineageNode:
    id: str
    filename: str | None
    description: str | None
    created_at: str | None
    parents: list[LineageNode] = field(default_factory=list)
    children: list[LineageNode] = field(default_factory=list)


def canonical_id(artifact_id: str) -> str:
    """IDs are 8 uppercase letters and digits; accept them typed in lowercase or with spaces."""
    return artifact_id.strip().upper()


_warned: set[str] = set()


def _warn_once(message: str) -> None:
    """Show a plan-usage warning once per process rather than on every publish."""
    import logging

    if not _warned:
        _warned.add(message)
        logging.getLogger("artifactum").warning("artifactum: %s", message)


class ArtifactumClient:
    def __init__(self, config: Config):
        self._base = config.server_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {config.api_token}"}

    def _get(self, path: str, **params: Any) -> Any:
        with httpx.Client(headers=self._headers) as c:
            r = c.get(f"{self._base}{path}", params=params)
        return self._handle(r)

    def _post(self, path: str, json: Any) -> Any:
        with httpx.Client(headers=self._headers) as c:
            r = c.post(f"{self._base}{path}", json=json)
        return self._handle(r)

    def _patch(self, path: str, json: Any) -> Any:
        with httpx.Client(headers=self._headers) as c:
            r = c.patch(f"{self._base}{path}", json=json)
        return self._handle(r)

    def download_export(self, dest: Path) -> int:
        """Stream the full registry export (a zip) to `dest`; returns its size in bytes."""
        size = 0
        timeout = httpx.Timeout(30.0, read=600.0)
        with (
            httpx.Client(headers=self._headers, timeout=timeout) as c,
            c.stream("GET", f"{self._base}/api/export") as r,
        ):
            if not r.is_success:
                r.read()
                self._handle(r)
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
                    size += len(chunk)
        return size

    @staticmethod
    def _handle(r: httpx.Response) -> Any:
        if r.status_code == 404:
            # /artifacts/ID, /artifacts/ID/run, /artifacts/ID/lineage: name the artifact, not the sub-path
            parts = r.url.path.strip("/").split("/")
            raise ArtifactNotFoundError(parts[1] if len(parts) > 1 and parts[0] == "artifacts" else parts[-1])
        if r.status_code == 401:
            raise AuthError(
                "Invalid or missing API key. It may have been revoked: "
                "make a new one in Settings, then run `atfm init`."
            )
        if r.status_code == 403:
            # e.g. publishing with a read-only key: the server says which key and why
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = None
            raise AuthError(detail if isinstance(detail, str) else "This API key isn't allowed to do that.")
        if r.status_code == 402:
            detail = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get(
                "detail"
            )
            if isinstance(detail, dict):
                raise PlanLimitError(detail.get("message") or "Artifact limit reached.", detail.get("upgrade_url"))
            raise PlanLimitError("Artifact limit reached for your plan.")
        if not r.is_success:
            raise ArtifactumError(f"Server error {r.status_code}: {r.text}")
        return r.json()

    def register_artifact(
        self,
        *,
        hash: str,
        gcs_url: str,
        size_bytes: int,
        content_type: str | None = None,
        parent_ids: list[str] | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        run_id: str | None = None,
        run: dict[str, Any] | None = None,
        docs: str | None = None,
        name: str | None = None,
    ) -> Registered:
        body: dict[str, Any] = {
            "hash": hash,
            "gcs_url": gcs_url,
            "size_bytes": size_bytes,
        }
        if content_type:
            body["content_type"] = content_type
        if parent_ids:
            body["parent_ids"] = [canonical_id(p) for p in parent_ids]
        if description:
            body["description"] = description
        if tags:
            body["tags"] = tags
        if run_id:
            body["run_id"] = run_id
        if run:
            body["run"] = run
        if name:
            body["name"] = name
        if docs:
            body["docs"] = docs
        data = self._post("/artifacts", body)
        if data.get("warning"):
            _warn_once(data["warning"])
        return Registered(data["id"], bool(data.get("existing")))

    def get_artifact(self, artifact_id: str) -> ArtifactMeta:
        data = self._get(f"/artifacts/{canonical_id(artifact_id)}")
        return ArtifactMeta(
            id=data["id"],
            hash=data["hash"],
            gcs_url=data["gcs_url"],
            content_type=data.get("content_type"),
            size_bytes=data.get("size_bytes"),
            description=data.get("description"),
            tags=data.get("tags", []),
            created_at=data.get("created_at"),
            owner_id=data.get("owner_id"),
            name=data.get("name"),
            superseded_by=data.get("superseded_by"),
            stale=bool(data.get("stale")),
        )

    def get_run(self, artifact_id: str) -> dict[str, Any] | None:
        return self._get(f"/artifacts/{canonical_id(artifact_id)}/run").get("run")

    def get_lineage(self, artifact_id: str) -> dict[str, Any]:
        return self._get(f"/artifacts/{canonical_id(artifact_id)}/lineage")

    def search(self, query: str, tags: list[str] | None = None) -> list[ArtifactMeta]:
        params: dict[str, Any] = {"q": query}
        if tags:
            params["tags"] = ",".join(tags)
        data = self._get("/artifacts/search", **params)
        return [self._meta(d) for d in data.get("results", [])]

    def get_recent(self) -> list[ArtifactMeta]:
        data = self._get("/artifacts/recent")
        return [self._meta(d) for d in data.get("results", [])]

    def update_artifact(
        self,
        artifact_id: str,
        *,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> ArtifactMeta:
        body: dict[str, Any] = {}
        if description is not None:
            body["description"] = description
        if tags is not None:
            body["tags"] = tags
        data = self._patch(f"/artifacts/{canonical_id(artifact_id)}", body)
        return self._meta(data)

    # ── Moving storage ───────────────────────────────────────────────────────────────

    def files_under(self, root: str) -> dict[str, Any]:
        """Your stored files under a location: {"artifacts": [{id, hash, url}], "code": [{hash, url}]}"""
        return self._get("/artifacts/storage/files", prefix=root)

    def move_storage(self, old_root: str, new_root: str) -> dict[str, int]:
        """Repoint your records from one location to another, once the files have been copied."""
        return self._post("/artifacts/storage/move", {"from_prefix": old_root, "to_prefix": new_root})

    @staticmethod
    def _meta(data: dict[str, Any]) -> ArtifactMeta:
        return ArtifactMeta(
            id=data["id"],
            hash=data["hash"],
            gcs_url=data["gcs_url"],
            content_type=data.get("content_type"),
            size_bytes=data.get("size_bytes"),
            description=data.get("description"),
            tags=data.get("tags", []),
            created_at=data.get("created_at"),
            owner_id=data.get("owner_id"),
        )
