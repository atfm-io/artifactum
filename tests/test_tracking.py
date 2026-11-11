import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import artifactum
from artifactum import tracking
from artifactum.client import ArtifactMeta
from artifactum.config import Config
from artifactum.provenance import git_info, redact_argv, strip_credentials


@pytest.fixture(autouse=True)
def fresh_scope() -> None:
    tracking.reset()


class FakeClient:
    """Stands in for ArtifactumClient: records registrations, resolves any ID."""

    registered: list[dict[str, Any]] = []

    def __init__(self, config: Config):
        pass

    def get_artifact(self, artifact_id: str) -> Any:
        return ArtifactMeta(
            id=artifact_id,
            hash="h-" + artifact_id,
            gcs_url="gs://b/x",
            content_type=None,
            size_bytes=None,
            description=None,
        )

    def register_artifact(self, **kwargs: Any) -> str:
        FakeClient.registered.append(kwargs)
        return f"OUT{len(FakeClient.registered):05d}"


@pytest.fixture
def fake_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    FakeClient.registered = []
    config = Config(api_token="t", server_url="http://x", storage="gs://bucket", cache_dir=str(tmp_path / "c"))
    uploads: list[str] = []
    monkeypatch.setattr("artifactum.client.ArtifactumClient", FakeClient)
    monkeypatch.setattr("artifactum.config.load_config", lambda: config)
    monkeypatch.setattr("artifactum.storage.GCSStorage.check", lambda self: None)
    monkeypatch.setattr("artifactum.storage.GCSStorage.upload", lambda self, local, url: uploads.append(url))
    # Cache hit for every artifact, so artifact() never downloads
    monkeypatch.setattr("artifactum.cache.Cache.get", lambda self, h: tmp_path / h)
    return FakeClient.registered


def _file(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_text(name)
    return p


def test_reads_become_parents(tmp_path: Path, fake_backend: list[dict[str, Any]]) -> None:
    artifactum.artifact("AAAAAAAA")
    artifactum.artifact("BBBBBBBB")
    artifactum.artifact("AAAAAAAA")
    artifactum.publish(_file(tmp_path, "out.csv"))
    assert fake_backend[0]["parent_ids"] == ["AAAAAAAA", "BBBBBBBB"]


def test_explicit_parents_override(tmp_path: Path, fake_backend: list[dict[str, Any]]) -> None:
    artifactum.artifact("AAAAAAAA")
    artifactum.publish(_file(tmp_path, "a.csv"), parents=["CCCCCCCC"])
    artifactum.publish(_file(tmp_path, "b.csv"), parents=[])
    artifactum.publish(_file(tmp_path, "c.csv"), parent="DDDDDDDD")
    assert [r["parent_ids"] for r in fake_backend] == [["CCCCCCCC"], [], ["DDDDDDDD"]]


def test_step_scopes_reads_and_runs(tmp_path: Path, fake_backend: list[dict[str, Any]]) -> None:
    artifactum.artifact("OUTSIDE1")
    with artifactum.step("join"):
        artifactum.artifact("INSIDE01")
        artifactum.publish(_file(tmp_path, "a.csv"))
        artifactum.publish(_file(tmp_path, "b.csv"))
    artifactum.publish(_file(tmp_path, "c.csv"))

    a, b, c = fake_backend
    assert a["parent_ids"] == ["INSIDE01"]
    assert c["parent_ids"] == ["OUTSIDE1"]
    # Same run for both outputs of the step; full run record only sent once
    assert a["run_id"] == b["run_id"] != c["run_id"]
    assert a["run"]["name"] == "join" and b["run"] is None
    assert c["run"] is not None


def test_step_as_decorator(tmp_path: Path, fake_backend: list[dict[str, Any]]) -> None:
    @artifactum.step()
    def build(src: str) -> None:
        artifactum.artifact(src)
        artifactum.publish(_file(tmp_path, src + ".csv"))

    build("AAAAAAAA")
    build("BBBBBBBB")
    assert [r["parent_ids"] for r in fake_backend] == [["AAAAAAAA"], ["BBBBBBBB"]]
    assert fake_backend[0]["run"]["name"] == "build"
    assert fake_backend[0]["run_id"] != fake_backend[1]["run_id"]


def test_run_captures_script_snapshot(
    tmp_path: Path, fake_backend: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _file(tmp_path, "pipeline.py")
    monkeypatch.setattr(sys, "argv", [str(script), "--api-token", "s3cret", "--rows=10"])
    artifactum.publish(_file(tmp_path, "out.csv"))
    run = fake_backend[0]["run"]
    assert run["entrypoint"] == str(script.resolve())
    assert run["argv"] == ["--api-token", "***", "--rows=10"]
    assert run["code_url"].startswith("gs://bucket/") and run["code_url"].endswith("/pipeline.py")
    assert run["python_version"] and isinstance(run["packages"], list)


def test_machine_details_can_be_left_out(
    tmp_path: Path, fake_backend: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from artifactum.config import load_config

    load_config().capture_machine = False
    monkeypatch.setattr(sys, "argv", [str(_file(tmp_path, "pipeline.py")), "--sample", "PATIENT-123"])
    artifactum.publish(_file(tmp_path, "out.csv"))
    run = fake_backend[0]["run"]
    assert not {"argv", "hostname", "os_user", "platform"} & run.keys()
    assert run["python_version"] and "packages" in run  # the code's own details still go


def test_capture_failure_does_not_block_publish(
    tmp_path: Path, fake_backend: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(**_: Any) -> None:
        raise RuntimeError("no git for you")

    monkeypatch.setattr("artifactum.provenance.capture_environment", boom)
    monkeypatch.setattr("artifactum.provenance.code_snapshot", boom)
    assert artifactum.publish(_file(tmp_path, "out.csv"))
    assert "entrypoint" not in fake_backend[0]["run"]


def test_redact_argv() -> None:
    assert redact_argv(["--password", "pw", "--key=abc", "-v", "file.csv"]) == [
        "--password",
        "***",
        "--key=***",
        "-v",
        "file.csv",
    ]


def test_strip_credentials() -> None:
    assert strip_credentials("https://user:ghp_tok@github.com/org/repo.git") == "https://github.com/org/repo.git"
    assert strip_credentials("git@github.com:org/repo.git") == "git@github.com:org/repo.git"


def test_git_info(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-b", "main")
    git("remote", "add", "origin", "https://u:tok@github.com/org/repo.git")
    script = _file(tmp_path, "train.py")
    git("add", ".")
    # Signing off: the scratch repo must not depend on the developer's git signing setup
    git("-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-m", "init")

    info = git_info(script)
    assert info["git_path"] == "train.py"
    assert info["git_branch"] == "main"
    assert info["git_remote"] == "https://github.com/org/repo.git"
    assert info["git_dirty"] is False and len(info["git_commit"]) == 40

    script.write_text("changed")
    assert git_info(script)["git_dirty"] is True
