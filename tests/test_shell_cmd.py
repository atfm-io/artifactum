"""Shell commands: atfm get / publish / run, with lineage recorded across separate commands."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from artifactum import tracking
from artifactum.cli.main import app
from tests.test_tracking import FakeClient, fake_backend  # noqa: F401  (fixture)

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracking, "runs_dir", lambda: tmp_path / "runs")
    monkeypatch.delenv("ARTIFACTUM_RUN", raising=False)
    tracking.reset()


def atfm(*args: str, monkeypatch: pytest.MonkeyPatch | None = None) -> Any:
    """Run one command as if it were its own process: tracking state comes from env + state file."""
    tracking.reset()
    return runner.invoke(app, list(args))


def test_a_shell_run_records_inputs_across_commands(tmp_path: Path, fake_backend, monkeypatch) -> None:  # noqa: F811
    start = atfm("run", "start", "align reads")
    assert start.exit_code == 0 and start.stdout.startswith("export ARTIFACTUM_RUN=")
    run_id = start.stdout.strip().split("=", 1)[1]
    monkeypatch.setenv("ARTIFACTUM_RUN", run_id)

    got = atfm("get", "REFGENOM")
    assert got.exit_code == 0 and got.stdout.strip() == str(tmp_path / "h-REFGENOM")  # just the path
    atfm("get", "READS001")

    out = tmp_path / "aligned.bam"
    out.write_text("bam")
    script = tmp_path / "align.sh"
    script.write_text("bwa mem ...")
    published = atfm("publish", str(out), "-d", "Aligned reads", "-t", "bam", "--code", str(script))
    assert published.exit_code == 0, published.output
    assert published.stdout.strip() == "OUT00001"  # just the ID

    call = fake_backend[0]
    assert call["parent_ids"] == ["REFGENOM", "READS001"]
    assert call["run_id"] == run_id and call["run"]["name"] == "align reads"
    assert call["run"]["entrypoint"].endswith("align.sh") and "packages" not in call["run"]

    # A second output in the same run reuses the run without resending it
    out2 = tmp_path / "qc.html"
    out2.write_text("qc")
    atfm("publish", str(out2))
    assert fake_backend[1]["run_id"] == run_id and fake_backend[1]["run"] is None

    assert atfm("run", "end").stdout.strip() == "unset ARTIFACTUM_RUN"
    assert not (tmp_path / "runs" / f"{run_id}.json").exists()


def test_explicit_parents_and_no_parents(tmp_path: Path, fake_backend) -> None:  # noqa: F811
    f = tmp_path / "x.csv"
    f.write_text("x")
    atfm("publish", str(f), "-p", "PARENT01", "-p", "PARENT02", "--name", "x-table")
    assert fake_backend[0]["parent_ids"] == ["PARENT01", "PARENT02"] and fake_backend[0]["name"] == "x-table"
    atfm("get", "IGNORED1")
    atfm("publish", str(f), "--no-parents")
    assert not fake_backend[1].get("parent_ids")


def test_outside_a_run_publish_hints_how_to_record_parents(tmp_path: Path, fake_backend) -> None:  # noqa: F811
    f = tmp_path / "y.csv"
    f.write_text("y")
    result = atfm("publish", str(f))
    assert result.exit_code == 0 and "start a run" in result.stderr


# ── --json ───────────────────────────────────────────────────────────────────

import json  # noqa: E402


def test_get_and_publish_json(tmp_path: Path, fake_backend, monkeypatch) -> None:  # noqa: F811
    start = atfm("run", "start", "qc")
    monkeypatch.setenv("ARTIFACTUM_RUN", start.stdout.strip().split("=", 1)[1])
    got = atfm("get", "REFGENOM", "--json")
    assert got.exit_code == 0 and json.loads(got.stdout) == {"id": "REFGENOM", "path": str(tmp_path / "h-REFGENOM")}

    out = tmp_path / "qc.csv"
    out.write_text("qc")
    published = atfm("publish", str(out), "--json")
    assert published.exit_code == 0, published.output
    body = json.loads(published.stdout)  # stdout is only the JSON; hints stay on stderr
    assert body["id"] == "OUT00001" and body["file"] == str(out.resolve())
    assert body["parents"] == ["REFGENOM"] and body["run_id"]

    status = json.loads(atfm("run", "status", "--json").stdout)
    assert status["name"] == "qc" and status["inputs"] == ["REFGENOM"]


def test_publish_json_outside_a_run(tmp_path: Path, fake_backend) -> None:  # noqa: F811
    f = tmp_path / "z.csv"
    f.write_text("z")
    body = json.loads(atfm("publish", str(f), "-p", "PARENT01", "--json").stdout)
    assert body["parents"] == ["PARENT01"] and body["run_id"] is None
    assert json.loads(atfm("run", "status", "--json").stdout) == {"run_id": None, "name": None, "started_at": None, "inputs": []}


def test_describe_and_log_json(fake_backend, monkeypatch) -> None:  # noqa: F811
    from tests.test_tracking import FakeClient

    parents = {"CHILD001": [{"id": "PARENT01"}], "PARENT01": []}
    monkeypatch.setattr(FakeClient, "get_lineage", lambda self, aid: {"parents": parents[aid]}, raising=False)
    monkeypatch.setattr(FakeClient, "get_run", lambda self, aid: {"name": "make child"}, raising=False)

    described = json.loads(atfm("describe", "CHILD001", "--json").stdout)
    assert described["id"] == "CHILD001" and described["hash"] == "h-CHILD001" and described["run"] == {"name": "make child"}

    tree = json.loads(atfm("log", "CHILD001", "--json").stdout)
    assert tree["id"] == "CHILD001" and [p["id"] for p in tree["parents"]] == ["PARENT01"]
    assert tree["parents"][0]["parents"] == []
