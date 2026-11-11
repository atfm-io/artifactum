"""atfm browse — Two-panel Textual TUI for artifact discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pyperclip
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static, Tab, Tabs

from artifactum.client import ArtifactMeta, ArtifactumClient
from artifactum.config import load_config


def _age(dt_str: str | None) -> str:
    if not dt_str:
        return "?"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        delta = datetime.now(UTC) - dt
        s = int(delta.total_seconds())
        if s < 3600:
            return f"{s // 60}m"
        if s < 86400:
            return f"{s // 3600}h"
        return f"{s // 86400}d"
    except Exception:
        return "?"


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n //= 1024
    return f"{n:.0f} PB"


class EditFieldScreen(ModalScreen[str | None]):
    """Generic single-field edit modal."""

    def __init__(self, prompt: str, current: str):
        super().__init__()
        self._prompt = prompt
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-dialog"):
            yield Label(self._prompt)
            yield Input(value=self._current, id="field-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_key(self, event: Any) -> None:
        if event.key == "escape":
            self.dismiss(None)


class ArtifactumApp(App):
    CSS = """
    #left-panel {
        width: 40%;
        border-right: solid $primary;
    }
    #detail {
        width: 60%;
        padding: 1 2;
        height: 100%;
    }
    #tag-filter {
        display: none;
        margin: 0 1;
    }
    #tag-filter.visible {
        display: block;
    }
    #edit-dialog {
        background: $surface;
        border: solid $primary;
        padding: 2 4;
        width: 60%;
        height: auto;
        margin: 4 20;
    }
    ListView > ListItem.--highlight {
        background: $accent;
    }
    """

    TITLE = "Artifactum"
    SUB_TITLE = "Preview: work in progress. Use the web app to search and trace lineage."

    BINDINGS = [
        Binding("e", "edit_description", "Edit description"),
        Binding("t", "edit_tags", "Edit tags"),
        Binding("y", "copy_id", "Copy ID"),
        Binding("o", "open_artifact", "Open/print path"),
        Binding("enter", "open_artifact", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, client: ArtifactumClient):
        super().__init__()
        self._client = client
        self._artifacts: list[ArtifactMeta] = []
        self._sort_mode = "recent"
        self._selected: ArtifactMeta | None = None
        self._tag_filter = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left-panel"):
                yield Tabs(
                    Tab("Recent", id="recent"),
                    Tab("Published", id="published"),
                    Tab("Tag A→Z", id="tag"),
                )
                yield Input(placeholder="Filter by tag…", id="tag-filter")
                yield ListView(id="artifact-list")
            yield Static(id="detail", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.notify(
            "The terminal browser is a preview: it shows your 20 most recent artifacts and has no search yet.",
            title="Work in progress",
            timeout=6,
        )
        self._load_artifacts()

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab is None:
            return
        self._sort_mode = event.tab.id  # type: ignore[assignment]
        tag_input = self.query_one("#tag-filter", Input)
        if self._sort_mode == "tag":
            tag_input.add_class("visible")
            tag_input.focus()
        else:
            tag_input.remove_class("visible")
            self._tag_filter = ""
            tag_input.value = ""
            self.query_one("#artifact-list", ListView).focus()
        if self._sort_mode == "recent":
            self._load_artifacts()
        else:
            self._apply_sort()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "tag-filter":
            self._tag_filter = event.value.strip().lower()
            self._apply_sort()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "tag-filter":
            # Move focus back to the list so arrow keys work
            self.query_one("#artifact-list", ListView).focus()

    def _load_artifacts(self) -> None:
        try:
            self._artifacts = self._client.get_recent()
        except Exception as e:
            self.query_one("#detail", Static).update(f"[red]Error loading artifacts: {e}[/red]")
            return
        self._apply_sort()

    def _apply_sort(self) -> None:
        artifacts = self._artifacts

        if self._sort_mode == "tag":
            if self._tag_filter:
                artifacts = [a for a in artifacts if any(self._tag_filter in t.lower() for t in a.tags)]
            artifacts = sorted(
                artifacts,
                key=lambda a: (a.tags[0].lower() if a.tags else "\xff", a.created_at or ""),
            )
        elif self._sort_mode == "published":
            artifacts = sorted(artifacts, key=lambda a: a.created_at or "", reverse=True)

        self._refresh_list(artifacts)

    def _refresh_list(self, artifacts: list[ArtifactMeta]) -> None:
        lv = self.query_one("#artifact-list", ListView)
        lv.clear()

        prev_tag: str | None = None
        for a in artifacts:
            if self._sort_mode == "tag":
                first_tag = a.tags[0] if a.tags else "(untagged)"
                if first_tag != prev_tag:
                    # Group header — non-interactive separator
                    header = ListItem(Label(f"[bold yellow] {first_tag} [/bold yellow]"))
                    header.disabled = True
                    lv.append(header)
                    prev_tag = first_tag

            filename = a.gcs_url.rsplit("/", 1)[-1] if a.gcs_url else a.id
            age = _age(a.created_at)
            tags_str = f"  [{', '.join(a.tags)}]" if a.tags and self._sort_mode != "tag" else ""
            item = ListItem(Label(f"  {a.id}  {filename:<28}  {age:>4}{tags_str}"))
            item.data = a  # type: ignore[attr-defined]
            lv.append(item)

        # Select first non-header item
        for i, child in enumerate(lv.children):
            if not getattr(child, "disabled", False):
                lv.index = i
                break

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None or getattr(event.item, "disabled", False):
            return
        a: ArtifactMeta | None = getattr(event.item, "data", None)
        if a is None:
            return
        self._selected = a
        self._render_detail(a)

    def _render_detail(self, a: ArtifactMeta) -> None:
        filename = a.gcs_url.rsplit("/", 1)[-1] if a.gcs_url else a.id
        tags_str = ", ".join(a.tags) if a.tags else "—"
        detail = (
            f"[bold]ID:[/bold]          {a.id}\n"
            f"[bold]Description:[/bold] {a.description or '—'}\n"
            f"[bold]Tags:[/bold]        {tags_str}\n"
            f"[bold]Size:[/bold]        {_fmt_bytes(a.size_bytes)}\n"
            f"[bold]Type:[/bold]        {a.content_type or '—'}\n"
            f"[bold]File:[/bold]        {filename}\n"
            f"[bold]Published:[/bold]   {a.created_at or '—'}\n\n"
            f"[bold]GCS URL:[/bold]     {a.gcs_url}\n\n"
            f"[dim]\\[e] description  \\[t] tags  \\[y] copy ID  \\[o] GCS path[/dim]"
        )
        self.query_one("#detail", Static).update(detail)

    def _apply_edit(self, artifact_id: str, **fields: Any) -> None:
        """Apply a saved edit to every copy of the artifact held here. The list can be
        reloaded while a row is highlighted, so the selection may be an older copy."""
        for a in [*self._artifacts, self._selected]:
            if a is not None and a.id == artifact_id:
                for key, value in fields.items():
                    setattr(a, key, value)
        if self._selected is not None:
            self._render_detail(self._selected)

    def action_edit_description(self) -> None:
        if self._selected is None:
            return

        def on_result(value: str | None) -> None:
            if value is not None and self._selected:
                try:
                    self._client.update_artifact(self._selected.id, description=value)
                    self._apply_edit(self._selected.id, description=value)
                except Exception as e:
                    self.notify(f"Error updating: {e}", severity="error")

        self.push_screen(
            EditFieldScreen("Edit description (Enter to save, Escape to cancel):", self._selected.description or ""),
            on_result,
        )

    def action_edit_tags(self) -> None:
        if self._selected is None:
            return

        current_tags = ", ".join(self._selected.tags)

        def on_result(value: str | None) -> None:
            if value is not None and self._selected:
                new_tags = [t.strip() for t in value.split(",") if t.strip()]
                try:
                    self._client.update_artifact(self._selected.id, tags=new_tags)
                    self._apply_edit(self._selected.id, tags=new_tags)
                    self._apply_sort()
                except Exception as e:
                    self.notify(f"Error updating: {e}", severity="error")

        self.push_screen(
            EditFieldScreen("Edit tags — comma-separated (Enter to save, Escape to cancel):", current_tags),
            on_result,
        )

    def action_copy_id(self) -> None:
        if self._selected:
            try:
                pyperclip.copy(self._selected.id)
                self.notify(f"Copied {self._selected.id} to clipboard")
            except Exception:
                self.notify(f"ID: {self._selected.id}")

    def action_open_artifact(self) -> None:
        if self._selected:
            self.notify(f"GCS: {self._selected.gcs_url}")


def run_browse() -> None:
    config = load_config()
    client = ArtifactumClient(config)
    ArtifactumApp(client).run()
