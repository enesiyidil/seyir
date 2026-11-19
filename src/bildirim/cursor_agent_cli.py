"""Thin wrapper around cursor-agent CLI ask mode."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from bildirim.config import project_root

# Prompt marker so hooks can ignore these sessions even if the spawn window closed.
GROK_SENTINEL = "[[bildirim-grok]]"

_ids_lock = threading.Lock()


def cursor_api_key() -> str | None:
    env = (os.environ.get("CURSOR_API_KEY") or "").strip()
    if env:
        return env
    path = project_root() / "data" / "cursor_api.key"
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            return raw
    return None


def cursor_agent_bin() -> str | None:
    override = (os.environ.get("CURSOR_AGENT_BIN") or "").strip()
    if override and Path(override).is_file():
        return override
    found = shutil.which("cursor-agent")
    if found:
        return found
    home = Path.home() / ".local" / "bin" / "cursor-agent"
    return str(home) if home.is_file() else None


def cli_ids_path() -> Path:
    return project_root() / "data" / "cli_session_ids.txt"


def cli_spawn_path() -> Path:
    return project_root() / "data" / "cli_spawn.json"


def remember_cli_session(conversation_id: str) -> None:
    cid = (conversation_id or "").strip()
    if not cid:
        return
    path = cli_ids_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _ids_lock:
        existing: set[str] = set()
        if path.is_file():
            existing = {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
        if cid in existing:
            return
        with path.open("a", encoding="utf-8") as fh:
            fh.write(cid + "\n")


def is_cli_session(conversation_id: str) -> bool:
    cid = (conversation_id or "").strip()
    if not cid:
        return False
    path = cli_ids_path()
    if not path.is_file():
        return False
    with _ids_lock:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() == cid:
                return True
    return False


def cli_spawn_active() -> bool:
    path = cli_spawn_path()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    until = float(data.get("until") or 0)
    return time.time() < until


def begin_cli_spawn(seconds: float) -> None:
    path = cli_spawn_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"until": time.time() + max(5.0, seconds)}) + "\n",
        encoding="utf-8",
    )


def end_cli_spawn(grace: float = 2.0) -> None:
    begin_cli_spawn(grace)


def cursor_agent_ask(
    prompt: str,
    *,
    model: str,
    timeout: int = 180,
    cwd: Path | None = None,
) -> tuple[str | None, str]:
    binary = cursor_agent_bin()
    if not binary:
        return None, "cursor_agent_missing"
    api_key = cursor_api_key()
    if not api_key:
        return None, "no_cursor_api_key"
    marked = prompt if GROK_SENTINEL in prompt else f"{GROK_SENTINEL}\n{prompt}"
    env = os.environ.copy()
    env["CURSOR_API_KEY"] = api_key
    env.pop("CURSOR_SESSION_TOKEN", None)
    cmd = [
        binary,
        "--print",
        "-f",
        "--mode",
        "ask",
        "--model",
        model,
        "--output-format",
        "text",
        marked,
    ]
    begin_cli_spawn(timeout + 30)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(cwd or project_root()),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "cursor_agent_timeout"
    except OSError as exc:
        return None, f"cursor_agent_os:{exc.__class__.__name__}"
    finally:
        end_cli_spawn()

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0 and not out:
        detail = err.splitlines()[-1] if err else f"exit_{proc.returncode}"
        return None, f"cursor_agent_fail:{detail[:160]}"
    lines = [
        ln
        for ln in out.splitlines()
        if ln.strip()
        and "Workspace Trust" not in ln
        and GROK_SENTINEL not in ln
        and not ln.strip().startswith("⚠")
    ]
    text = "\n".join(lines).strip()
    return (text or None), ("empty_agent_output" if not text else "")
