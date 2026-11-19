"""Append/read short evidence traces for IDE sessions (for /ozet)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bildirim.config import project_root


def traces_dir() -> Path:
    path = project_root() / "data" / "cursor_traces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe(conversation_id: str) -> str:
    return "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in conversation_id
    )[:120]


def append_event(conversation_id: str, kind: str, text: str, **extra: Any) -> None:
    if not conversation_id:
        return
    path = traces_dir() / f"{_safe(conversation_id)}.jsonl"
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "text": (text or "")[:4000],
        **{k: v for k, v in extra.items() if v is not None},
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_recent(conversation_id: str, limit: int = 40) -> list[dict[str, Any]]:
    path = traces_dir() / f"{_safe(conversation_id)}.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def evidence_text(conversation_id: str, *, meta: dict[str, Any] | None = None) -> str:
    rows = read_recent(conversation_id, 50)
    parts: list[str] = []
    if meta:
        parts.append(
            f"proje={meta.get('project')} short={meta.get('short_id')} "
            f"stop={meta.get('stop_requested')} active={meta.get('active')}"
        )
    if not rows:
        parts.append("(Bu oturum için henüz iz kaydı yok.)")
        return "\n".join(parts)
    for row in rows:
        kind = row.get("kind") or "?"
        text = (row.get("text") or "").strip().replace("\n", " ")
        if len(text) > 500:
            text = text[:500] + "…"
        parts.append(f"[{row.get('ts','')[:19]}] {kind}: {text}")
    return "\n".join(parts)
