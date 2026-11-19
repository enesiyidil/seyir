"""Remember processed Mail message ids."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_path(project_root: Path) -> Path:
    return project_root / "data" / "processed_mail.json"


class ProcessedStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {"messages": {}}
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("messages"), dict):
                    self._data = loaded
            except json.JSONDecodeError:
                pass

    def has(self, message_id: str) -> bool:
        return message_id in self._data["messages"]

    def get(self, message_id: str) -> dict[str, Any] | None:
        item = self._data["messages"].get(message_id)
        return item if isinstance(item, dict) else None

    def put(self, message_id: str, record: dict[str, Any]) -> None:
        payload = dict(record)
        payload["saved_at"] = datetime.now(timezone.utc).isoformat()
        self._data["messages"][message_id] = payload
        self._flush()

    def find_by_telegram(self, telegram_message_id: int) -> dict[str, Any] | None:
        for item in self._data["messages"].values():
            if item.get("telegram_message_id") == telegram_message_id:
                return item
        return None

    def latest_alert(self) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        latest_key = ""
        for key, item in self._data["messages"].items():
            if not isinstance(item, dict):
                continue
            if item.get("kind") not in {"important", "meeting"}:
                continue
            if not item.get("body_preview"):
                continue
            stamp = str(item.get("saved_at") or key)
            if stamp >= latest_key:
                latest_key = stamp
                latest = item
        return latest

    def _flush(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)
