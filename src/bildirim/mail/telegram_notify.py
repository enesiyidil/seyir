"""Send mail alerts to the Telegram Mail topic."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from bildirim.config import Settings
from bildirim.mail.qwen import Classification
from bildirim.mail.rules import MailItem


def send_alert(
    settings: Settings,
    *,
    token: str,
    item: MailItem,
    classification: Classification,
) -> int:
    if settings.group_id is None:
        raise SystemExit("TELEGRAM_GROUP_ID eksik.")
    topic = settings.topics.get("mail")
    if topic is None:
        raise SystemExit("TELEGRAM_TOPIC_MAIL eksik.")

    if classification.kind == "meeting":
        text = (
            "📅 Toplantı\n"
            f"Konu: {classification.subject or item.subject}\n"
            f"Tarih: {classification.when or item.date_received}\n"
            f"Katılımcılar: {classification.participants or '—'}\n"
            f"Kimden: {item.sender}"
        )
    else:
        text = (
            "❗ Önemli mail\n"
            f"Kimden: {item.sender}\n"
            f"Konu: {classification.subject or item.subject}\n"
            'İçerik için bu mesaja "içerik" yaz.'
        )

    payload: dict[str, Any] = {
        "chat_id": settings.group_id,
        "message_thread_id": topic,
        "text": text[:3500],
        "disable_web_page_preview": True,
    }
    result = _api(token, "sendMessage", payload)
    message = result.get("result") or {}
    message_id = message.get("message_id")
    if not isinstance(message_id, int):
        raise RuntimeError(f"Telegram message_id yok: {result}")
    return message_id


def send_text(settings: Settings, *, token: str, text: str, reply_to: int | None = None) -> None:
    if settings.group_id is None:
        raise SystemExit("TELEGRAM_GROUP_ID eksik.")
    topic = settings.topics.get("mail")
    if topic is None:
        raise SystemExit("TELEGRAM_TOPIC_MAIL eksik.")
    payload: dict[str, Any] = {
        "chat_id": settings.group_id,
        "message_thread_id": topic,
        "text": text[:3500],
        "disable_web_page_preview": True,
    }
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    _api(token, "sendMessage", payload)


def _api(token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {exc.code}: {detail[:300]}") from exc
