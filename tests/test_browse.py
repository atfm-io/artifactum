"""The terminal browser (atfm browse), driven with keypresses through Textual's test pilot."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pyperclip
from textual.widgets import Input, ListView, Static

import artifactum
from artifactum.cli.tui import ArtifactumApp
from artifactum.client import ArtifactumClient
from artifactum.config import load_config
from tests.conftest import Registry


def publish_three(tmp_path: Path) -> list[str]:
    ids = []
    for name, tags in (("counts.csv", ["rna-seq"]), ("model.pkl", ["models"]), ("qc.html", ["rna-seq", "qc"])):
        (tmp_path / name).write_text(name)
        ids.append(artifactum.publish(tmp_path / name, description=f"The {name}", tags=tags, parents=[]))
    return ids


def browse(registry: Registry, script) -> None:
    """Open the browser against the fake registry and run `script(app, pilot)`."""

    async def run() -> None:
        app = ArtifactumApp(ArtifactumClient(load_config(registry.config_path)))
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await script(app, pilot)

    asyncio.run(run())


def listed(app: ArtifactumApp) -> list[str]:
    """The artifact IDs in the list, top to bottom (group headers skipped)."""
    return [item.data.id for item in app.query_one("#artifact-list", ListView).children if hasattr(item, "data")]


def detail(app: ArtifactumApp) -> str:
    return str(app.query_one("#detail", Static).render())


def test_shows_recent_artifacts_newest_first_with_details(registry: Registry, tmp_path: Path) -> None:
    counts, model, qc = publish_three(tmp_path)

    async def script(app, pilot):
        assert listed(app) == [qc, model, counts]
        assert qc in detail(app) and "The qc.html" in detail(app)
        await pilot.press("down")
        assert "The model.pkl" in detail(app)

    browse(registry, script)


def test_filter_by_tag(registry: Registry, tmp_path: Path) -> None:
    counts, model, qc = publish_three(tmp_path)

    async def script(app, pilot):
        app.query_one("Tabs").active = "tag"
        await pilot.pause()
        assert app.query_one("#tag-filter", Input).has_focus
        await pilot.press(*"rna")
        await pilot.pause()
        assert set(listed(app)) == {counts, qc}
        await pilot.press("enter")  # back to the list
        assert app.query_one("#artifact-list", ListView).has_focus

        app.query_one("Tabs").active = "recent"  # leaving the tab clears the filter
        await pilot.pause()
        assert listed(app) == [qc, model, counts]

    browse(registry, script)


def test_edit_description_and_tags(registry: Registry, tmp_path: Path) -> None:
    *_, qc = publish_three(tmp_path)

    async def replace(pilot, key: str, text: str, submit: str = "enter") -> None:
        await pilot.press(key)
        await pilot.pause()  # the dialog opens
        await pilot.press("end", "ctrl+u", *text)  # clear the field and type
        await pilot.pause()
        await pilot.press(submit)
        await pilot.pause()

    async def script(app, pilot):
        await replace(pilot, "e", "Weekly QC")
        await replace(pilot, "t", "qc, weekly")
        await replace(pilot, "e", "Not saved", submit="escape")  # Escape cancels
        assert "Weekly QC" in detail(app) and "qc, weekly" in detail(app)

    browse(registry, script)
    stored = registry.server.artifacts[qc]
    assert stored["description"] == "Weekly QC" and stored["tags"] == ["qc", "weekly"]


def test_copy_the_id_or_show_the_path(registry: Registry, tmp_path: Path, monkeypatch) -> None:
    *_, qc = publish_three(tmp_path)
    copied: list[str] = []
    monkeypatch.setattr(pyperclip, "copy", copied.append)

    async def script(app, pilot):
        await pilot.press("y", "o")
        await pilot.pause()

    browse(registry, script)
    assert copied == [qc]


def test_a_server_error_is_shown_instead_of_the_list(registry: Registry) -> None:
    registry.server.down = True

    async def script(app, pilot):
        assert listed(app) == [] and "Error loading artifacts" in detail(app)

    browse(registry, script)
