"""What people actually do with Artifactum, end to end against a fake server and bucket.

Only the network and the bucket are faked (tests/fakes.py); the client, HTTP error
handling, hashing, the cache, lineage tracking and the CLI all run for real.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

import pytest

import artifactum
from artifactum.exceptions import ArtifactNotFoundError, ArtifactumError, AuthError, PlanLimitError
from tests.conftest import Registry
from tests.fakes import atfm

# Every journey runs twice: files in a Google Cloud Storage bucket, and in a shared directory
pytestmark = pytest.mark.parametrize("registry", ["gcs", "local"], indirect=True)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ── Sharing a file with a teammate ───────────────────────────────────────────────


def test_a_teammate_reads_what_was_published(registry: Registry, tmp_path: Path) -> None:
    """Publish on one machine; fetch it by ID on another; the second read comes from the cache."""
    table = write(tmp_path / "work" / "counts.csv", "gene,count\nBRCA1,12\n")
    artifact_id = artifactum.publish(table, description="Raw counts", tags=["rna-seq"])

    stored = registry.server.artifacts[artifact_id]
    assert stored["description"] == "Raw counts" and stored["tags"] == ["rna-seq"]
    assert stored["content_type"] == "text/csv" and stored["size_bytes"] == table.stat().st_size

    registry.configure(cache_dir=str(tmp_path / "teammate-cache"))  # another machine
    path = Path(artifactum.artifact(artifact_id.lower()))  # IDs work in lowercase too
    assert path.read_text() == table.read_text()
    assert path.is_relative_to(tmp_path / "teammate-cache")

    assert artifactum.artifact(artifact_id) == str(path)
    assert registry.downloads == 1  # the second read hit the cache


def test_a_corrupted_download_is_rejected_and_not_cached(registry: Registry, tmp_path: Path) -> None:
    artifact_id = artifactum.publish(write(tmp_path / "model.pkl", "weights"))
    registry.configure(cache_dir=str(tmp_path / "other-cache"))
    registry.stored(registry.server.artifacts[artifact_id]["gcs_url"]).write_text("tampered")

    with pytest.raises(ArtifactNotFoundError):
        artifactum.artifact(artifact_id)
    assert not any((tmp_path / "other-cache").rglob("*.pkl"))


def test_lineage_is_recorded_from_what_a_step_reads(registry: Registry, tmp_path: Path) -> None:
    raw = artifactum.publish(write(tmp_path / "raw.csv", "a"), parents=[])
    ref = artifactum.publish(write(tmp_path / "ref.fa", "b"), parents=[])

    with artifactum.step("normalise"):
        artifactum.artifact(raw)
        artifactum.artifact(ref)
        out = artifactum.publish(write(tmp_path / "normalised.csv", "c"))
    assert registry.server.artifacts[out]["parent_ids"] == [raw, ref]

    tree = json.loads(atfm("log", out, "--json").stdout)
    assert [p["id"] for p in tree["parents"]] == [raw, ref]


# ── Versions ─────────────────────────────────────────────────────────────────────


def test_reading_an_old_version_or_a_stale_result_warns(registry: Registry, tmp_path: Path, caplog) -> None:
    v1 = artifactum.publish(write(tmp_path / "v1" / "model.pkl", "v1"), name="churn-model")
    with artifactum.step("score"):
        artifactum.artifact(v1)
        scores = artifactum.publish(write(tmp_path / "scores.csv", "s"))
    v2 = artifactum.publish(write(tmp_path / "v2" / "model.pkl", "v2"), name="churn-model", parents=[])

    with caplog.at_level(logging.WARNING, logger="artifactum"):
        artifactum.artifact(v1)
        artifactum.artifact(scores)
    assert f"{v1} is an older version of churn-model; the newest is {v2}" in caplog.text
    assert f"{scores} was built from inputs that have newer versions" in caplog.text


# ── Docs and code ────────────────────────────────────────────────────────────────


def test_docs_from_a_readme_file_or_inline_text(registry: Registry, tmp_path: Path) -> None:
    readme = write(tmp_path / "README.md", "# Counts\nOne row per gene.")
    a = artifactum.publish(write(tmp_path / "a.csv", "a"), docs=str(readme))
    b = artifactum.publish(write(tmp_path / "b.csv", "b"), docs="Filtered to protein-coding genes.")
    assert registry.server.artifacts[a]["docs"] == "# Counts\nOne row per gene."
    assert registry.server.artifacts[b]["docs"] == "Filtered to protein-coding genes."


def test_the_script_that_made_a_file_can_be_read_back(registry: Registry, tmp_path: Path) -> None:
    script = write(tmp_path / "align.sh", "bwa mem ref.fa reads.fq > out.sam\n")
    out = write(tmp_path / "out.sam", "sam")
    published = atfm("publish", str(out), "--code", str(script), "-d", "Aligned reads")
    assert published.exit_code == 0, published.output

    shown = atfm("code", published.stdout.strip())
    assert shown.exit_code == 0 and "bwa mem ref.fa reads.fq" in shown.stdout

    described = atfm("describe", published.stdout.strip())
    assert "Aligned reads" in described.stdout and "Produced by" in described.stdout
    assert "Python" not in described.stdout  # a shell run has no Python version to show


def test_turning_off_code_capture_uploads_no_code(registry: Registry, tmp_path: Path) -> None:
    registry.configure(capture_code=False)
    out = atfm("publish", str(write(tmp_path / "x.csv", "x")), "--code", str(write(tmp_path / "make.py", "print()")))
    run = next(iter(registry.server.runs.values()))
    assert out.exit_code == 0 and "code_url" not in run
    assert not list(registry.store_root.rglob("make.py"))


# ── When things go wrong ─────────────────────────────────────────────────────────


def test_a_wrong_token_says_so(registry: Registry, tmp_path: Path) -> None:
    registry.configure(api_token="atfm_revoked")
    with pytest.raises(AuthError):
        artifactum.publish(write(tmp_path / "x.csv", "x"))

    result = atfm("get", "ART00001")
    assert result.exit_code == 1 and "Invalid or missing API key" in result.stderr


def test_an_unknown_id_is_a_clear_error_not_a_traceback(registry: Registry) -> None:
    for command in (["get", "NOPE1234"], ["describe", "NOPE1234"], ["log", "NOPE1234"], ["code", "NOPE1234"]):
        result = atfm(*command)
        assert result.exit_code == 1 and "NOPE1234" in result.stderr, command


def test_reaching_the_plan_limit_explains_how_to_upgrade(registry: Registry, tmp_path: Path) -> None:
    registry.server.artifact_limit = 1
    artifactum.publish(write(tmp_path / "a.csv", "a"))
    with pytest.raises(PlanLimitError) as e:
        artifactum.publish(write(tmp_path / "b.csv", "b"))
    assert e.value.upgrade_url == "http://registry.test/settings"

    result = atfm("publish", str(tmp_path / "b.csv"))
    assert result.exit_code == 1 and "Free plan's limit" in result.stderr
    assert registry.server.publish_count() == 1 and not list(registry.store_root.rglob("b.csv"))


def test_the_server_being_down_is_reported(registry: Registry, tmp_path: Path) -> None:
    registry.server.down = True
    with pytest.raises(ArtifactumError, match="503"):
        artifactum.artifact("ART00001")


def test_a_parent_that_does_not_exist_is_refused(registry: Registry, tmp_path: Path) -> None:
    result = atfm("publish", str(write(tmp_path / "x.csv", "x")), "-p", "nope0000")
    assert result.exit_code == 1 and "NOPE0000" in result.stderr
    assert registry.server.publish_count() == 0


# ── Finding things and leaving ───────────────────────────────────────────────────


def test_search_by_text_and_tag(registry: Registry, tmp_path: Path) -> None:
    qc = artifactum.publish(write(tmp_path / "qc.html", "q"), description="QC report", tags=["qc", "rna-seq"])
    artifactum.publish(write(tmp_path / "qc2.html", "r"), description="QC report", tags=["qc"])
    artifactum.publish(write(tmp_path / "m.pkl", "m"), description="Model")

    assert len(artifactum.search("qc")) == 2
    assert [a.id for a in artifactum.search("qc", tags=["rna-seq"])] == [qc]


def test_export_downloads_the_whole_registry(registry: Registry, tmp_path: Path) -> None:
    artifactum.publish(write(tmp_path / "a.csv", "a"))
    dest = tmp_path / "backup.zip"
    result = atfm("export", "-o", str(dest))
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(dest) as z:
        assert [a["id"] for a in json.loads(z.read("artifacts.json"))] == ["ART00001"]

    registry.configure(api_token="atfm_revoked")
    assert atfm("export", "-o", str(tmp_path / "again.zip")).exit_code == 1


def test_files_that_share_a_name_are_not_versions_unless_named(registry: Registry, tmp_path: Path, capsys) -> None:
    """Script 1 writes test.csv; script 2 reads it and writes a different test.csv."""
    first = artifactum.publish(write(tmp_path / "one" / "test.csv", "a\n1\n"))
    assert f"artifactum: Published test.csv as {first}" in capsys.readouterr().err

    second = artifactum.publish(write(tmp_path / "two" / "test.csv", "a\n1\n2\n"), parents=[first])
    assert registry.server.artifacts[first]["name"] is None
    assert registry.server.artifacts[second]["name"] is None

    named = artifactum.publish(write(tmp_path / "three" / "test.csv", "a\n3\n"), name="scores")
    assert registry.server.artifacts[named]["name"] == "scores"


def test_publishing_the_same_content_again_says_so_and_uploads_nothing(
    registry: Registry, tmp_path: Path, capsys
) -> None:
    original = artifactum.publish(write(tmp_path / "a" / "out.csv", "same\n"))
    capsys.readouterr()

    again = artifactum.publish(write(tmp_path / "b" / "copy.csv", "same\n"), description="ignored")
    assert again == original
    err = capsys.readouterr().err
    assert f"copy.csv is already published as {original} (same content), so nothing was uploaded" in err
    stored = registry.server.artifacts[original]["gcs_url"]
    assert registry.stored(stored).exists()
    assert not registry.stored(stored.replace("out.csv", "copy.csv")).exists()  # no second copy


def test_a_read_only_key_says_so_when_publishing(registry: Registry, tmp_path: Path) -> None:
    registry.server.read_only_key = "CI"
    with pytest.raises(AuthError, match='The API key "CI" is read-only'):
        artifactum.publish(write(tmp_path / "out.csv", "x\n"))
