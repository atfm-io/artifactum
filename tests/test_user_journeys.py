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
    assert registry.bucket.downloads == 1  # the second read hit the cache


def test_a_corrupted_download_is_rejected_and_not_cached(registry: Registry, tmp_path: Path) -> None:
    artifact_id = artifactum.publish(write(tmp_path / "model.pkl", "weights"))
    registry.configure(cache_dir=str(tmp_path / "other-cache"))
    registry.bucket.path(registry.server.artifacts[artifact_id]["gcs_url"]).write_text("tampered")

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
    assert not list(registry.bucket.root.rglob("make.py"))


# ── When things go wrong ─────────────────────────────────────────────────────────


def test_a_wrong_token_says_so(registry: Registry, tmp_path: Path) -> None:
    registry.configure(api_token="atfm_revoked")
    with pytest.raises(AuthError):
        artifactum.publish(write(tmp_path / "x.csv", "x"))

    result = atfm("get", "ART00001")
    assert result.exit_code == 1 and "Invalid or missing API token" in result.stderr


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
    assert registry.server.publish_count() == 1 and not list(registry.bucket.root.rglob("b.csv"))


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


# ── First-time setup ─────────────────────────────────────────────────────────────


def test_init_writes_the_config_and_keeps_the_token_on_a_rerun(tmp_path: Path, monkeypatch) -> None:
    from artifactum.cli import init_cmd
    from artifactum.config import load_config, save_config

    config_path = tmp_path / ".artifactum" / "config.toml"
    monkeypatch.setattr(init_cmd, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(init_cmd, "load_config", lambda: load_config(config_path))
    monkeypatch.setattr(init_cmd, "save_config", lambda c: save_config(c, config_path))

    def answer(answers: dict[str, str]):
        def ask(prompt: str, default: str | None = None, password: bool = False) -> str:
            for start, value in answers.items():
                if prompt.startswith(start):
                    return value if value != "<default>" else (default or "")
            raise AssertionError(f"unexpected prompt {prompt!r}")
        return ask

    cache = tmp_path / "cache"
    monkeypatch.setattr(init_cmd.Prompt, "ask", answer({
        "Server URL": "<default>", "API token": "atfm_first", "GCS bucket": "gs://lab/atfm",
        "Local cache directory": str(cache), "Cache size limit": "5",
    }))
    assert atfm("init").exit_code == 0
    config = load_config(config_path)
    assert (config.server_url, config.api_token, config.gcs_bucket, config.cache_limit_gb) == (
        "https://atfm.io", "atfm_first", "gs://lab/atfm", 5.0)
    assert cache.is_dir()

    # Re-running to change the bucket: an empty token keeps the saved one; a bad size falls back
    monkeypatch.setattr(init_cmd.Prompt, "ask", answer({
        "Server URL": "<default>", "API token": "", "GCS bucket": "gs://lab/new",
        "Local cache directory": "<default>", "Cache size limit": "lots",
    }))
    atfm("init")
    config = load_config(config_path)
    assert (config.api_token, config.gcs_bucket, config.cache_limit_gb) == ("atfm_first", "gs://lab/new", 2.0)


def test_commands_before_setup_say_to_run_init(tmp_path: Path, monkeypatch) -> None:
    from artifactum import config as config_mod

    real_load = config_mod.load_config
    monkeypatch.setattr(config_mod, "load_config", lambda: real_load(tmp_path / "missing.toml"))
    result = atfm("describe", "ART00001")
    assert result.exit_code == 1 and "atfm init" in result.stderr
