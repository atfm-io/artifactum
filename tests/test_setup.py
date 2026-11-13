"""First-time setup: atfm init, and what happens before it's run."""

from __future__ import annotations

from pathlib import Path

from tests.fakes import atfm


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
    monkeypatch.setattr(
        init_cmd.Prompt,
        "ask",
        answer(
            {
                "Server URL": "<default>",
                "API token": "atfm_first",
                "Storage location": "gs://lab/atfm",
                "Local cache directory": str(cache),
                "Cache size limit": "5",
            }
        ),
    )
    assert atfm("init").exit_code == 0
    config = load_config(config_path)
    assert (config.server_url, config.api_token, config.storage, config.cache_limit_gb) == (
        "https://atfm.io",
        "atfm_first",
        "gs://lab/atfm",
        5.0,
    )
    assert cache.is_dir()

    # Re-running to switch to a directory (saved as an absolute path).
    # An empty token keeps the saved one; a bad size falls back.
    monkeypatch.setattr(
        init_cmd.Prompt,
        "ask",
        answer(
            {
                "Server URL": "<default>",
                "API token": "",
                "Storage location": "~/atfm-files",
                "Local cache directory": "<default>",
                "Cache size limit": "lots",
            }
        ),
    )
    atfm("init")
    config = load_config(config_path)
    home_path = (Path.home() / "atfm-files").resolve().as_posix()
    assert (config.api_token, config.storage, config.cache_limit_gb) == ("atfm_first", f"file://{home_path}", 2.0)


def test_commands_before_setup_say_to_run_init(tmp_path: Path, monkeypatch) -> None:
    from artifactum import config as config_mod

    real_load = config_mod.load_config
    monkeypatch.setattr(config_mod, "load_config", lambda: real_load(tmp_path / "missing.toml"))
    result = atfm("describe", "ART00001")
    assert result.exit_code == 1 and "atfm init" in result.stderr


def test_init_with_flags_asks_nothing_and_creates_the_folder(tmp_path: Path, monkeypatch) -> None:
    """The one line the website shows after sign-up: token and storage given, no questions."""
    from artifactum.cli import init_cmd
    from artifactum.config import load_config, save_config

    config_path = tmp_path / ".artifactum" / "config.toml"
    monkeypatch.setattr(init_cmd, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(init_cmd, "load_config", lambda: load_config(config_path))
    monkeypatch.setattr(init_cmd, "save_config", lambda c: save_config(c, config_path))

    def no_questions(*args, **kwargs):
        raise AssertionError("init asked a question")

    monkeypatch.setattr(init_cmd.Prompt, "ask", no_questions)
    files = tmp_path / "atfm-files"
    result = atfm("init", "--token", "atfm_abc", "--storage", str(files))
    assert result.exit_code == 0, result.output
    # Rich wraps at 80 columns, splitting long paths (macOS temp dirs) mid-path, so compare without whitespace
    assert files.is_dir() and f"Created{files}" in "".join(result.stdout.split())

    config = load_config(config_path)
    assert (config.api_token, config.storage, config.server_url) == (
        "atfm_abc",
        f"file://{files.as_posix()}",
        "https://atfm.io",
    )


def test_version_flag_prints_the_installed_version(capsys) -> None:
    from importlib.metadata import version

    import pytest

    from artifactum.cli.main import main

    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.strip() == f"atfm {version('artifactum')}"
