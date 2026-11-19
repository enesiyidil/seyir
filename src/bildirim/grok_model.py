"""Pick the top available Grok model from cursor-agent --list-models."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from bildirim.config import project_root

FALLBACK_GROK_MODEL = "grok-4.7-xhigh"
CACHE_TTL_SEC = 3600

_EFFORT_RANK = {
    "xhigh": 4,
    "max": 4,
    "high": 3,
    "medium": 2,
    "med": 2,
    "low": 1,
}

_MODEL_LINE_RE = re.compile(
    r"^(?P<id>(?:cursor-)?grok-[A-Za-z0-9._-]+)\s+-\s+(?P<label>.+)$"
)
_VERSION_RE = re.compile(r"(?:cursor-)?grok-(?P<ver>\d+(?:\.\d+)*)", re.I)


def cache_path() -> Path:
    return project_root() / "data" / "grok_model_cache.json"


def resolve_top_grok(*, force_refresh: bool = False) -> str:
    override = (os.environ.get("BILDIRIM_GROK_MODEL") or "").strip()
    if override:
        return override

    cached = _read_cache()
    now = time.time()
    if (
        not force_refresh
        and cached
        and (now - float(cached.get("ts") or 0)) < CACHE_TTL_SEC
        and cached.get("model")
    ):
        return str(cached["model"])

    models = list_grok_model_ids()
    picked = pick_top_grok(models) or FALLBACK_GROK_MODEL
    _write_cache(picked, models)
    return picked


def list_grok_model_ids() -> list[str]:
    binary = _cursor_agent_bin()
    if not binary:
        return []
    api_key = _cursor_api_key()
    env = os.environ.copy()
    if api_key:
        env["CURSOR_API_KEY"] = api_key
    try:
        proc = subprocess.run(
            [binary, "--list-models"],
            capture_output=True,
            text=True,
            timeout=45,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    ids: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        m = _MODEL_LINE_RE.match(line)
        if m:
            ids.append(m.group("id"))
            continue
        if re.fullmatch(r"(?:cursor-)?grok-[A-Za-z0-9._-]+", line):
            ids.append(line)
    return list(dict.fromkeys(ids))


def pick_top_grok(model_ids: list[str]) -> str | None:
    scored: list[tuple[tuple[Any, ...], str]] = []
    for mid in model_ids:
        key = _score(mid)
        if key is None:
            continue
        scored.append((key, mid))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def _score(model_id: str) -> tuple[Any, ...] | None:
    low = model_id.lower()
    if "grok" not in low:
        return None
    vm = _VERSION_RE.search(low)
    if not vm:
        return None
    ver_parts = tuple(int(p) for p in vm.group("ver").split("."))
    effort = 0
    for name, rank in _EFFORT_RANK.items():
        if re.search(rf"(?:^|-){name}(?:-|$)", low):
            effort = max(effort, rank)
    is_fast = 0 if low.endswith("-fast") or "-fast-" in low else 1
    return (ver_parts, effort, is_fast)


def _read_cache() -> dict[str, Any] | None:
    path = cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_cache(model: str, models: list[str]) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": time.time(),
        "model": model,
        "candidates": models[:80],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _cursor_agent_bin() -> str | None:
    override = (os.environ.get("CURSOR_AGENT_BIN") or "").strip()
    if override and Path(override).is_file():
        return override
    found = shutil.which("cursor-agent")
    if found:
        return found
    home = Path.home() / ".local" / "bin" / "cursor-agent"
    return str(home) if home.is_file() else None


def _cursor_api_key() -> str | None:
    env = (os.environ.get("CURSOR_API_KEY") or "").strip()
    if env:
        return env
    path = project_root() / "data" / "cursor_api.key"
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            return raw
    return None
