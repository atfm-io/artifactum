"""Storing files in a shared directory or a bucket: what's specific to each backend."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import artifactum
from artifactum.exceptions import StorageError
from artifactum.storage import GCSStorage, LocalStorage, normalise_location, storage_for
from tests.conftest import Registry
from tests.fakes import atfm


def flat(text: str) -> str:
    """Output with Rich's line wrapping undone."""
    return " ".join(text.split())


def test_what_people_type_becomes_a_storage_url(tmp_path: Path) -> None:
    assert normalise_location("gs://lab-bucket/atfm/") == "gs://lab-bucket/atfm"
    assert normalise_location("lab-bucket/atfm") == "gs://lab-bucket/atfm"  # how buckets were given before
    assert normalise_location(str(tmp_path / "shared")) == f"file://{tmp_path.as_posix()}/shared"
    assert normalise_location("~/atfm") == f"file://{(Path.home() / 'atfm').resolve().as_posix()}"
    assert isinstance(storage_for("/groups/lab/atfm"), LocalStorage)
    assert isinstance(storage_for("gs://b"), GCSStorage)

    with pytest.raises(StorageError, match="Unsupported"):
        storage_for("s3://bucket/atfm")
    with pytest.raises(StorageError, match="atfm init"):
        storage_for("")


@pytest.mark.parametrize("registry", ["local"], indirect=True)
def test_files_land_in_the_shared_directory_once(registry: Registry, tmp_path: Path) -> None:
    table = tmp_path / "my counts.csv"
    table.write_text("gene,count\n")
    first = artifactum.publish(table, parents=[])
    second = artifactum.publish(table, parents=[])  # the same content again

    url = registry.server.artifacts[first]["gcs_url"]
    assert url == registry.server.artifacts[second]["gcs_url"]
    assert url.endswith("/my counts.csv")  # names aren't percent-encoded
    stored = [p.name for p in registry.store_root.rglob("*") if p.is_file()]
    assert stored.count("my counts.csv") == 1 and not [n for n in stored if n.startswith(".upload-")]

    described = "".join(atfm("describe", first).stdout.split())  # long values wrap across lines
    assert "".join(str(registry.stored(url)).split()) in described and "file://" not in described  # a path, not a URL


@pytest.mark.parametrize("registry", ["local"], indirect=True)
def test_a_missing_shared_directory_stops_the_publish_before_it_is_recorded(registry: Registry, tmp_path: Path) -> None:
    registry.store_root.rmdir()  # e.g. the drive isn't mounted
    out = tmp_path / "x.csv"
    out.write_text("x")
    result = atfm("publish", str(out))
    assert result.exit_code == 1 and "doesn't exist" in result.stderr
    assert registry.server.publish_count() == 0
    assert not registry.store_root.exists()  # not silently created on the local disk


@pytest.mark.parametrize("registry", ["local"], indirect=True)
def test_a_machine_without_the_shared_directory_says_so(registry: Registry, tmp_path: Path) -> None:
    out = tmp_path / "x.csv"
    out.write_text("x")
    artifact_id = artifactum.publish(out)
    registry.stored(registry.server.artifacts[artifact_id]["gcs_url"]).unlink()
    registry.configure(cache_dir=str(tmp_path / "laptop-cache"))

    result = atfm("get", artifact_id)
    assert result.exit_code == 1 and "mounted" in result.stderr


def test_an_object_missing_from_the_bucket_says_so(registry: Registry, tmp_path: Path) -> None:
    out = tmp_path / "x.csv"
    out.write_text("x")
    artifact_id = artifactum.publish(out)
    registry.stored(registry.server.artifacts[artifact_id]["gcs_url"]).unlink()
    registry.configure(cache_dir=str(tmp_path / "laptop-cache"))

    result = atfm("get", artifact_id)
    assert result.exit_code == 1 and "isn't in the bucket" in result.stderr


def test_a_bucket_without_the_gcs_extra_explains_what_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "google.cloud.storage", None)  # as if not installed
    with pytest.raises(StorageError, match=r"artifactum\[gcs\]"):
        GCSStorage("gs://lab/atfm").check()


# ── Moving to new storage ────────────────────────────────────────────────────────


def _publish_with_lineage(tmp_path: Path) -> tuple[str, str]:
    raw = tmp_path / "raw.csv"
    raw.write_text("a,b\n")
    script = tmp_path / "clean.sh"
    script.write_text("clean raw.csv > clean.csv\n")
    raw_id = artifactum.publish(raw, parents=[])
    clean = tmp_path / "clean.csv"
    clean.write_text("a\n")
    result = atfm("publish", str(clean), "-p", raw_id, "--code", str(script))
    assert result.exit_code == 0, result.output
    return raw_id, result.stdout.strip()


@pytest.mark.parametrize("registry", ["local"], indirect=True)
def test_moving_from_a_private_folder_to_a_shared_one(registry: Registry, tmp_path: Path) -> None:
    """Someone tries it in ~/atfm-files, then moves to the lab's shared directory for their team."""
    raw_id, clean_id = _publish_with_lineage(tmp_path)
    old_files = sorted(p.relative_to(registry.store_root) for p in registry.store_root.rglob("*") if p.is_file())
    shared = tmp_path / "groups" / "lab" / "atfm"
    shared.mkdir(parents=True)

    result = atfm("storage", "move", str(shared))
    assert result.exit_code == 0, result.output
    # Two code snapshots: the script that published raw.csv (here, pytest) and clean.sh
    assert "Moved 2 artifacts and 2 code snapshots" in flat(result.stdout)

    for artifact_id in (raw_id, clean_id):
        assert registry.server.artifacts[artifact_id]["gcs_url"].startswith(f"file://{shared.as_posix()}/")
    new_files = sorted(p.relative_to(shared) for p in shared.rglob("*") if p.is_file())
    assert new_files == old_files  # the same layout, and the old copies are still there
    assert all((registry.store_root / f).is_file() for f in old_files)

    # A teammate (a fresh cache) reads from the shared directory, code snapshot included
    registry.configure(cache_dir=str(tmp_path / "teammate-cache"))
    assert Path(artifactum.artifact(clean_id)).read_text() == "a\n"
    assert "clean raw.csv" in atfm("code", clean_id).stdout
    # and new publishes go to the new place
    new = tmp_path / "new.csv"
    new.write_text("n")
    assert registry.server.artifacts[artifactum.publish(new)]["gcs_url"].startswith(f"file://{shared.as_posix()}/")


@pytest.mark.parametrize("registry", ["local"], indirect=True)
def test_moving_from_a_directory_to_a_bucket(
    registry: Registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.fakes import FakeBucket

    bucket = FakeBucket(tmp_path / "gcs")
    monkeypatch.setattr(GCSStorage, "_client", lambda self: bucket)
    raw_id, clean_id = _publish_with_lineage(tmp_path)

    assert atfm("storage", "move", "gs://lab-bucket/atfm").exit_code == 0
    url = registry.server.artifacts[clean_id]["gcs_url"]
    assert url.startswith("gs://lab-bucket/atfm/") and (tmp_path / "gcs" / url.removeprefix("gs://")).is_file()
    registry.configure(cache_dir=str(tmp_path / "laptop-cache"))
    assert Path(artifactum.artifact(raw_id)).read_text() == "a,b\n"


@pytest.mark.parametrize("registry", ["local"], indirect=True)
def test_a_move_that_fails_part_way_changes_nothing(registry: Registry, tmp_path: Path) -> None:
    raw_id, clean_id = _publish_with_lineage(tmp_path)
    before = {i: a["gcs_url"] for i, a in registry.server.artifacts.items()}
    registry.stored(before[clean_id]).write_text("edited by hand")
    shared = tmp_path / "shared2"
    shared.mkdir()

    result = atfm("storage", "move", str(shared))
    assert result.exit_code == 1 and "has changed since it was published" in flat(result.stderr)
    assert {i: a["gcs_url"] for i, a in registry.server.artifacts.items()} == before
    from artifactum.config import load_config

    assert load_config(registry.config_path).storage == LocalStorage.url_of(registry.store_root)


@pytest.mark.parametrize("registry", ["local"], indirect=True)
def test_moving_needs_a_real_new_place(registry: Registry, tmp_path: Path) -> None:
    same = atfm("storage", "move", str(registry.store_root))
    assert same.exit_code == 1 and "already in" in flat(same.stderr)
    missing = atfm("storage", "move", str(tmp_path / "not-made-yet"))
    assert missing.exit_code == 1 and "doesn't exist" in flat(missing.stderr)


@pytest.mark.parametrize("registry", ["local"], indirect=True)
def test_a_team_admin_moves_the_teams_files(registry: Registry, tmp_path: Path) -> None:
    _publish_with_lineage(tmp_path)
    shared = tmp_path / "team-share"
    shared.mkdir()
    result = atfm("storage", "move", str(shared), "--team")
    assert result.exit_code == 0, result.stderr
    assert registry.server.listed_as_team and registry.server.moved_as_team
    out = flat(result.stdout)
    assert "Moved 2 artifacts" in out and f"atfm storage move {shared}" in out  # what to tell teammates

    # Without --team, only your own files are asked for
    (tmp_path / "back").mkdir()
    assert atfm("storage", "move", str(tmp_path / "back")).exit_code == 0
    assert not registry.server.listed_as_team
