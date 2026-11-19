"""Classify mail with the local oMLX / Qwen server."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bildirim.mail.rules import MailItem, is_external, looks_like_calendar


@dataclass(frozen=True)
class Classification:
    kind: str  # meeting | important | noise | ignore
    subject: str
    when: str
    participants: str
    reason: str


def _omlx_api_key() -> str:
    env = os.environ.get("OMLX_API_KEY", "").strip()
    if env:
        return env
    path = Path.home() / ".omlx" / "settings.json"
    if not path.is_file():
        raise SystemExit("OMLX_API_KEY yok ve ~/.omlx/settings.json bulunamadı.")
    data = json.loads(path.read_text(encoding="utf-8"))
    key = ((data.get("auth") or {}).get("api_key") or "").strip()
    if not key:
        raise SystemExit("oMLX API anahtarı boş.")
    return key


def _base_url() -> str:
    return os.environ.get("OMLX_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _model() -> str:
    return os.environ.get("OMLX_MODEL", "Qwen3.8-27B-oQ6e-mtp")


def classify(item: MailItem) -> Classification:
    hint = []
    if looks_like_calendar(item):
        hint.append("calendar_hint=true")
    if is_external(item):
        hint.append("external_sender=true")
    system = (
        "Sen şirket posta sınıflandırıcısısın. Yalnızca JSON döndür. "
        "Alanlar: kind, subject, when, participants, reason. "
        "kind değerleri: meeting, important, noise, ignore. "
        "meeting: toplantı daveti; when ve participants doldur. "
        "important: müşteri veya kaçırılmaması gereken iş maili; when/participants boş olabilir. "
        "noise: Bitbucket, Confluence, RSVP, ürün bülteni, otomasyon. "
        "ignore: emin değilsen. "
        "subject alanına kısa Türkçe konu özeti yaz."
    )
    user = (
        f"hints: {', '.join(hint) or 'none'}\n"
        f"from: {item.sender}\n"
        f"date: {item.date_received}\n"
        f"subject: {item.subject}\n"
        f"body:\n{item.body[:3000]}\n"
    )
    payload = {
        "model": _model(),
        "temperature": 0.1,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    data = _post_chat(payload)
    content = (
        (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
    )
    parsed = _parse_json_content(content)
    kind = str(parsed.get("kind", "ignore")).strip().lower()
    if kind not in {"meeting", "important", "noise", "ignore"}:
        kind = "ignore"
    return Classification(
        kind=kind,
        subject=str(parsed.get("subject") or item.subject).strip(),
        when=str(parsed.get("when") or "").strip(),
        participants=str(parsed.get("participants") or "").strip(),
        reason=str(parsed.get("reason") or "").strip(),
    )


def _post_chat(payload: dict[str, Any], *, timeout: float = 180) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{_base_url()}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_omlx_api_key()}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"oMLX HTTP {exc.code}: {detail[:300]}") from exc


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}
