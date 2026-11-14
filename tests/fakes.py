"""A fake Artifactum server and GCS bucket, wired in at the network and storage boundaries.

Everything above them (the client, HTTP error handling, hashing, the cache, lineage
tracking and the CLI) runs for real, so tests can follow what a user actually does.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

TOKEN = "atfm_test_token"
SERVER_URL = "http://registry.test"


@dataclass
class FakeServer:
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    # Set to a number to make the server refuse publishes past it (402), like a plan limit
    artifact_limit: int | None = None
    down: bool = False
    # Set to answer like the real server does for a read-only API key: reads work, writes 403
    read_only_key: str | None = None
    # What the last storage listing / move asked for (yours, or the team's with --team)
    listed_as_team: bool = False
    moved_as_team: bool = False

    def publish_count(self) -> int:
        return len(self.artifacts)

    # ── Versions, worked out the way the real server does ────────────────────────
    def _newest(self, a: dict[str, Any]) -> str:
        if a["name"] is None:  # no name, no versions
            return a["id"]
        same = [b for b in self.artifacts.values() if b["name"] == a["name"]]
        return max(same, key=lambda b: b["seq"])["id"]

    def _view(self, a: dict[str, Any]) -> dict[str, Any]:
        newest = self._newest(a)
        superseded = newest if newest != a["id"] else None
        stale = superseded is None and any(
            self._newest(self.artifacts[p]) != p and self.artifacts[p]["name"] != a["name"] for p in a["parent_ids"]
        )
        return {k: v for k, v in a.items() if k not in ("seq", "parent_ids", "run_id")} | {
            "superseded_by": superseded,
            "stale": stale,
        }

    # ── HTTP ─────────────────────────────────────────────────────────────────────
    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            return httpx.Response(503, text="Service Unavailable")
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"detail": "Invalid token"})
        path, method = request.url.path, request.method
        if self.read_only_key and method not in ("GET", "HEAD"):
            detail = (
                f'The API key "{self.read_only_key}" is read-only. '
                "Use a key with full access to publish or change things."
            )
            return httpx.Response(403, json={"detail": detail})

        if method == "POST" and path == "/artifacts":
            return self._register(json.loads(request.content))
        if method == "GET" and path == "/artifacts/recent":
            recent = sorted(self.artifacts.values(), key=lambda a: a["seq"], reverse=True)[:20]
            return httpx.Response(200, json={"results": [self._view(a) for a in recent]})
        if method == "GET" and path == "/artifacts/search":
            q, tags = request.url.params.get("q", ""), request.url.params.get("tags")
            hits = [a for a in self.artifacts.values() if q.lower() in (a.get("description") or "").lower()]
            if tags:
                hits = [a for a in hits if set(tags.split(",")) <= set(a["tags"])]
            return httpx.Response(200, json={"results": [self._view(a) for a in hits]})
        if method == "GET" and path == "/api/export":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("artifacts.json", json.dumps(list(self.artifacts.values())))
            return httpx.Response(200, content=buf.getvalue())

        if method == "GET" and path == "/artifacts/storage/files":
            root = request.url.params["prefix"].rstrip("/") + "/"
            self.listed_as_team = request.url.params.get("team") == "true"
            return httpx.Response(200, json=self._files_under(root))
        if method == "POST" and path == "/artifacts/storage/move":
            body = json.loads(request.content)
            self.moved_as_team = bool(body.get("team"))
            return httpx.Response(200, json=self._move(body["from_prefix"], body["to_prefix"]))

        m = re.fullmatch(r"/artifacts/([A-Z0-9]{8})(/run|/lineage)?", path)
        if not m or m.group(1) not in self.artifacts:
            return httpx.Response(404, json={"detail": "Not found"})
        a = self.artifacts[m.group(1)]
        if m.group(2) == "/run":
            return httpx.Response(200, json={"run": self.runs.get(a["run_id"])})
        if m.group(2) == "/lineage":
            return httpx.Response(200, json={"parents": [{"id": p} for p in a["parent_ids"]]})
        if method == "PATCH":
            a.update(json.loads(request.content))
        return httpx.Response(200, json=self._view(a))

    # ── Moving storage (every artifact here belongs to the caller) ──────────────────
    def _code_under(self, root: str) -> list[dict[str, Any]]:
        return [r for r in self.runs.values() if (r.get("code_url") or "").startswith(root)]

    def _files_under(self, root: str) -> dict[str, Any]:
        return {
            "artifacts": [
                {"id": a["id"], "hash": a["hash"], "url": a["gcs_url"]}
                for a in self.artifacts.values()
                if a["gcs_url"].startswith(root)
            ],
            "code": [{"hash": r["code_hash"], "url": r["code_url"]} for r in self._code_under(root)],
        }

    def _move(self, old: str, new: str) -> dict[str, int]:
        old, new = old.rstrip("/") + "/", new.rstrip("/") + "/"
        moved = [a for a in self.artifacts.values() if a["gcs_url"].startswith(old)]
        for a in moved:
            a["gcs_url"] = new + a["gcs_url"].removeprefix(old)
        runs = self._code_under(old)
        for r in runs:
            r["code_url"] = new + r["code_url"].removeprefix(old)
        return {"artifacts": len(moved), "code": len(runs)}

    def _register(self, body: dict[str, Any]) -> httpx.Response:
        if self.artifact_limit is not None and self.publish_count() >= self.artifact_limit:
            return httpx.Response(
                402,
                json={
                    "detail": {
                        "message": f"You've reached the Free plan's limit of {self.artifact_limit} artifacts.",
                        "upgrade_url": f"{SERVER_URL}/settings",
                    }
                },
            )
        same = next((a for a in self.artifacts.values() if a["hash"] == body["hash"]), None)
        if same:  # like the server: identical content returns the existing artifact, unchanged
            return httpx.Response(201, json={"id": same["id"], "existing": True})
        missing = [p for p in body.get("parent_ids", []) if p not in self.artifacts]
        if missing:
            return httpx.Response(422, json={"detail": f"Unknown parent {missing[0]}"})
        seq = len(self.artifacts) + 1
        artifact_id = f"ART{seq:05d}"
        if body.get("run"):
            self.runs[body["run_id"]] = body["run"]
        self.artifacts[artifact_id] = {
            "id": artifact_id,
            "seq": seq,
            "hash": body["hash"],
            "gcs_url": body["gcs_url"],
            "size_bytes": body["size_bytes"],
            "content_type": body.get("content_type"),
            "description": body.get("description"),
            "tags": body.get("tags", []),
            "docs": body.get("docs"),
            "name": body.get("name"),
            "parent_ids": body.get("parent_ids", []),
            "run_id": body.get("run_id"),
            "created_at": f"2026-11-10T12:{seq:02d}:00Z",
        }
        return httpx.Response(201, json={"id": artifact_id, "existing": False})


class FakeBucket:
    """Stands in for a google.cloud.storage Client: objects are files under `root`."""

    def __init__(self, root: Path):
        self.root = root

    # The parts of storage.Client that GCSStorage uses
    def bucket(self, name: str) -> _Bucket:
        return _Bucket(self, name)


@dataclass
class _Bucket:
    store: FakeBucket
    name: str

    def blob(self, path: str) -> _Blob:
        return _Blob(self.store, self.store.root / self.name / path)


@dataclass
class _Blob:
    store: FakeBucket
    path: Path

    def upload_from_filename(self, filename: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(filename, self.path)

    def download_to_filename(self, filename: str) -> None:
        if not self.path.is_file():
            raise NotFound(str(self.path))
        shutil.copyfile(self.path, filename)


class NotFound(Exception):
    """Named like google.api_core.exceptions.NotFound, which is what GCSStorage looks for."""


# ── Running the CLI ──────────────────────────────────────────────────────────────


@dataclass
class Result:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


def atfm(*args: str) -> Result:
    """Run one command as if it were its own process: tracking state comes from env + state file."""
    from artifactum import tracking
    from artifactum.cli.main import main

    tracking.reset()
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            main(list(args))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return Result(code, out.getvalue(), err.getvalue())
