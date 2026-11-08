"""Capture what produced an artifact: code, git state and environment.

Everything here runs on the client. Only metadata (commit, paths, versions, the
code snapshot's hash and location) is sent to the Artifactum server; the code itself
is uploaded to the team's own bucket alongside the data.
"""

from __future__ import annotations

import getpass
import platform
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024
_SENSITIVE_ARG = re.compile(r"pass|secret|token|key|credential|auth", re.IGNORECASE)


@dataclass
class CodeSnapshot:
    filename: str
    content: bytes


def _ipython() -> Any | None:
    if "IPython" not in sys.modules:
        return None
    try:
        from IPython import get_ipython

        return get_ipython()
    except Exception:
        return None


def _script_path() -> Path | None:
    if not sys.argv or not sys.argv[0] or sys.argv[0] == "-c":
        return None
    path = Path(sys.argv[0]).expanduser()
    return path.resolve() if path.is_file() else None


def _notebook_path(ip: Any) -> str | None:
    # VS Code exposes the notebook path; classic Jupyter doesn't, reliably.
    path = ip.user_ns.get("__vsc_ipynb_file__") if ip is not None else None
    return str(path) if path else None


def _git(cwd: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=3, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def strip_credentials(url: str | None) -> str | None:
    """Remove user:password@ from http(s) remotes so tokens never leave the machine."""
    if not url:
        return url
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") and "@" in parts.netloc:
        return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))
    return url


def redact_argv(argv: list[str]) -> list[str]:
    """Mask values of arguments that look like secrets (--token=x, --password x)."""
    out: list[str] = []
    redact_next = False
    for arg in argv:
        if redact_next:
            out.append("***")
            redact_next = False
            continue
        if arg.startswith("-") and _SENSITIVE_ARG.search(arg):
            if "=" in arg:
                out.append(arg.split("=", 1)[0] + "=***")
            else:
                out.append(arg)
                redact_next = True
            continue
        out.append(arg)
    return out


def git_info(path: Path) -> dict[str, Any]:
    cwd = path if path.is_dir() else path.parent
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if top is None:
        return {}
    rel = None
    if path.is_file():
        try:
            rel = str(path.resolve().relative_to(Path(top).resolve()))
        except ValueError:
            pass
    status = _git(cwd, "status", "--porcelain", "--untracked-files=no")
    return {
        "git_commit": _git(cwd, "rev-parse", "HEAD"),
        "git_branch": _git(cwd, "rev-parse", "--abbrev-ref", "HEAD"),
        "git_remote": strip_credentials(_git(cwd, "remote", "get-url", "origin")),
        "git_path": rel,
        "git_dirty": bool(status),
    }


def _packages() -> list[str]:
    from importlib.metadata import distributions

    seen: dict[str, str] = {}
    for dist in distributions():
        name = dist.metadata["Name"]
        if name and name.lower() not in seen:
            seen[name.lower()] = f"{name}=={dist.version}"
    return sorted(seen.values(), key=str.lower)


# Details about the machine and person rather than the code; left out when capture_machine is off
MACHINE_FIELDS = ("argv", "platform", "hostname", "os_user")


def capture_environment(machine: bool = True) -> dict[str, Any]:
    """Describe the code location, git state and environment of this process."""
    ip = _ipython()
    script = _script_path()
    notebook = _notebook_path(ip)

    if ip is not None:
        entrypoint = notebook or "<notebook>"
        where = Path(notebook) if notebook else Path.cwd()
    elif script is not None:
        entrypoint = str(script)
        where = script
    else:
        entrypoint = "<interactive>"
        where = Path.cwd()

    try:
        user = getpass.getuser()
    except Exception:
        user = None

    env = {
        "entrypoint": entrypoint,
        "argv": redact_argv(sys.argv[1:]) if ip is None else [],
        **git_info(where),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "os_user": user,
        "packages": _packages(),
    }
    if not machine:
        for field in MACHINE_FIELDS:
            env.pop(field, None)
    return env


def code_snapshot() -> CodeSnapshot | None:
    """The code that is running: the script file, or the notebook's executed cells."""
    ip = _ipython()
    if ip is not None:
        history = getattr(ip, "history_manager", None)
        cells = list(getattr(history, "input_hist_raw", []) or [])[1:]
        if not cells:
            return None
        body = "\n\n".join(f"# In[{i}]:\n{src}" for i, src in enumerate(cells, start=1) if src.strip())
        name = Path(_notebook_path(ip) or "notebook").stem + ".py"
        return CodeSnapshot(name, body.encode()[:_MAX_SNAPSHOT_BYTES])

    script = _script_path()
    if script is None or script.stat().st_size > _MAX_SNAPSHOT_BYTES:
        return None
    return CodeSnapshot(script.name, script.read_bytes())
