"""IDE Agent conversation ↔ Telegram topic mapping + soft-stop flags."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bildirim.config import project_root


def default_path() -> Path:
    return project_root() / "data" / "cursor_sessions.json"


def stops_dir() -> Path:
    return project_root() / "data" / "cursor_stops"


def freeze_all_path() -> Path:
    return project_root() / "data" / "cursor_freeze_all"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sync_stop_file(conversation_id: str, requested: bool) -> None:
    folder = stops_dir()
    folder.mkdir(parents=True, exist_ok=True)
    # Safe filename: only alnum and dash
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in conversation_id)[
        :120
    ]
    path = folder / safe
    if requested:
        path.write_text(_now(), encoding="utf-8")
    elif path.exists():
        path.unlink()


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {
            "sessions": {},
            "active_id": None,
            "freeze_all": False,
        }
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("sessions"), dict):
                self._data = loaded
        except json.JSONDecodeError:
            pass

    def _flush(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def reload(self) -> None:
        with self._lock:
            self._load()

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._load()
            item = self._data["sessions"].get(conversation_id)
            return dict(item) if isinstance(item, dict) else None

    def find_by_short(self, short_id: str) -> tuple[str, dict[str, Any]] | None:
        needle = short_id.strip().lower()
        if not needle:
            return None
        with self._lock:
            self._load()
            for cid, item in self._data["sessions"].items():
                if not isinstance(item, dict):
                    continue
                if str(item.get("short_id", "")).lower() == needle:
                    return cid, dict(item)
                if cid.lower().startswith(needle):
                    return cid, dict(item)
        return None

    def find_by_topic(self, topic_id: int) -> tuple[str, dict[str, Any]] | None:
        with self._lock:
            self._load()
            for cid, item in self._data["sessions"].items():
                if isinstance(item, dict) and item.get("topic_id") == topic_id:
                    return cid, dict(item)
        return None

    def upsert(self, conversation_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            self._load()
            sessions: dict[str, Any] = self._data.setdefault("sessions", {})
            current = sessions.get(conversation_id)
            if not isinstance(current, dict):
                current = {
                    "short_id": conversation_id[:8],
                    "topic_id": None,
                    "title": "",
                    "project": "",
                    "stop_requested": False,
                    "started_at": _now(),
                    "last_at": _now(),
                    "active": True,
                }
            # Preserve an existing soft-stop flag unless explicitly overridden.
            if "stop_requested" not in fields and current.get("stop_requested"):
                fields = {**fields, "stop_requested": True}
            current.update(fields)
            current["last_at"] = _now()
            sessions[conversation_id] = current
            self._data["active_id"] = conversation_id
            self._flush()
            return dict(current)

    def set_stop(self, conversation_id: str, requested: bool = True) -> dict[str, Any] | None:
        with self._lock:
            self._load()
            item = self._data["sessions"].get(conversation_id)
            if not isinstance(item, dict):
                # Oturum henüz map’te yoksa bile flag tut (race / test).
                item = {
                    "short_id": conversation_id[:8],
                    "topic_id": None,
                    "title": "",
                    "project": "",
                    "stop_requested": requested,
                    "started_at": _now(),
                    "last_at": _now(),
                    "active": True,
                }
                self._data["sessions"][conversation_id] = item
            else:
                item["stop_requested"] = requested
                item["last_at"] = _now()
            if requested:
                self._data["active_id"] = conversation_id
            self._flush()
            _sync_stop_file(conversation_id, requested)
            return dict(item)

    def is_stop_requested(self, conversation_id: str) -> bool:
        if self.is_freeze_all():
            return True
        with self._lock:
            self._load()
            item = self._data["sessions"].get(conversation_id)
            if isinstance(item, dict) and item.get("stop_requested"):
                return True
        # Hook’ların bridge olmadan da görmesi için dosya bayrağı
        safe = "".join(
            ch if ch.isalnum() or ch in "-_" else "_" for ch in conversation_id
        )[:120]
        return (stops_dir() / safe).is_file()

    def should_block(self, conversation_id: str, parent_id: str = "") -> bool:
        if self.is_freeze_all():
            return True
        if conversation_id and self.is_stop_requested(conversation_id):
            return True
        if parent_id and self.is_stop_requested(parent_id):
            return True
        return False

    def clear_stop(self, conversation_id: str) -> None:
        self.set_stop(conversation_id, False)

    def set_freeze_all(self, enabled: bool) -> None:
        with self._lock:
            self._load()
            self._data["freeze_all"] = bool(enabled)
            self._flush()
        path = freeze_all_path()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_now(), encoding="utf-8")
            # Tüm bilinen oturumları da işaretle
            with self._lock:
                self._load()
                for cid, item in list(self._data.get("sessions", {}).items()):
                    if isinstance(item, dict):
                        item["stop_requested"] = True
                        _sync_stop_file(cid, True)
                self._flush()
        elif path.exists():
            path.unlink()

    def is_freeze_all(self) -> bool:
        if freeze_all_path().is_file():
            return True
        with self._lock:
            self._load()
            return bool(self._data.get("freeze_all"))

    def stop_all_active(self) -> list[str]:
        """Aktif oturumların hepsine stop; freeze_all da aç."""
        stopped: list[str] = []
        with self._lock:
            self._load()
            for cid, item in list(self._data.get("sessions", {}).items()):
                if not isinstance(item, dict):
                    continue
                if item.get("active", True) or item.get("stop_requested"):
                    item["stop_requested"] = True
                    item["last_at"] = _now()
                    _sync_stop_file(cid, True)
                    stopped.append(cid)
            self._data["freeze_all"] = True
            self._flush()
        freeze_all_path().parent.mkdir(parents=True, exist_ok=True)
        freeze_all_path().write_text(_now(), encoding="utf-8")
        return stopped

    def active(self) -> tuple[str, dict[str, Any]] | None:
        with self._lock:
            self._load()
            aid = self._data.get("active_id")
            if isinstance(aid, str):
                item = self._data["sessions"].get(aid)
                if isinstance(item, dict):
                    return aid, dict(item)
            # fallback: most recently updated active session
            best: tuple[str, dict[str, Any]] | None = None
            best_ts = ""
            for cid, item in self._data["sessions"].items():
                if not isinstance(item, dict) or not item.get("active", True):
                    continue
                ts = str(item.get("last_at") or "")
                if ts >= best_ts:
                    best_ts = ts
                    best = (cid, dict(item))
            return best

    def list_recent(self, limit: int = 10) -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            self._load()
            items = [
                (cid, dict(item))
                for cid, item in self._data["sessions"].items()
                if isinstance(item, dict)
            ]
        items.sort(key=lambda pair: str(pair[1].get("last_at") or ""), reverse=True)
        return items[:limit]

    def mark_ended(self, conversation_id: str) -> None:
        with self._lock:
            self._load()
            item = self._data["sessions"].get(conversation_id)
            if isinstance(item, dict):
                item["active"] = False
                item["last_at"] = _now()
                self._flush()
