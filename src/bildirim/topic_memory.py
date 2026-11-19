"""Per-Telegram-topic chat memory (jsonl)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bildirim.config import project_root

DEFAULT_KEEP = 80
DEFAULT_READ = 30


def chats_dir() -> Path:
    path = project_root() / "data" / "topic_chats"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(topic_id: int) -> Path:
    return chats_dir() / f"{int(topic_id)}.jsonl"


def append_turn(
    topic_id: int,
    role: str,
    text: str,
    *,
    mode: str = "",
) -> None:
    path = _path(topic_id)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "mode": mode,
        "text": (text or "")[:8000],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    _trim(path, keep=DEFAULT_KEEP)


def recent_turns(topic_id: int, limit: int = DEFAULT_READ) -> list[dict[str, Any]]:
    path = _path(topic_id)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) :]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("role") and item.get("text"):
            out.append(item)
    return out


def format_history(topic_id: int, limit: int = DEFAULT_READ) -> str:
    turns = recent_turns(topic_id, limit=limit)
    if not turns:
        return "(Bu konuda henüz sohbet yok.)"
    parts: list[str] = []
    for turn in turns:
        who = "Kullanıcı" if turn.get("role") == "user" else "Asistan"
        text = str(turn.get("text") or "").strip().replace("\n", " ")
        if len(text) > 600:
            text = text[:600] + "…"
        parts.append(f"{who}: {text}")
    return "\n".join(parts)


def _trim(path: Path, *, keep: int) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= keep:
        return
    path.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")
