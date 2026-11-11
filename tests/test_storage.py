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
