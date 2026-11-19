"""Minimal Telegram Bot HTTP helpers (no PTB dependency)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def api(
    token: str,
    method: str,
    payload: dict[str, Any],
    *,
    timeout: float = 20,
) -> dict[str, Any]:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {exc.code}: {detail[:400]}") from exc


def send_message(
    token: str,
    *,
    chat_id: int,
    text: str,
    message_thread_id: int | None = None,
    reply_to_message_id: int | None = None,
    parse_mode: str | None = None,
) -> int:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": True,
    }
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    if parse_mode:
        payload["parse_mode"] = parse_mode
    result = api(token, "sendMessage", payload)
    message = result.get("result") or {}
    mid = message.get("message_id")
    if not isinstance(mid, int):
        raise RuntimeError(f"message_id yok: {result}")
    return mid


def create_forum_topic(token: str, *, chat_id: int, name: str) -> int:
    result = api(
        token,
        "createForumTopic",
        {"chat_id": chat_id, "name": name[:128]},
        timeout=12,
    )
    topic = result.get("result") or {}
    thread_id = topic.get("message_thread_id")
    if not isinstance(thread_id, int):
        raise RuntimeError(f"message_thread_id yok: {result}")
    return thread_id
