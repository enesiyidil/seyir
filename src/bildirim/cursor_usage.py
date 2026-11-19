"""Cursor plan usage summary (cached session token; no Keychain popup in bot)."""

from __future__ import annotations

import getpass
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bildirim.config import project_root


@dataclass(frozen=True)
class UsageSummary:
    ok: bool
    text: str
    raw: dict[str, Any] | None = None


def session_token_path() -> Path:
    return project_root() / "data" / "cursor_session.token"


def fetch_usage_summary() -> UsageSummary:
    """Return a human-readable usage blurb for Telegram /limit."""
    token, auth_id, source = _resolve_access_token()
    if not token:
        return UsageSummary(False, "Kullanım sorgusu için CURSOR_SESSION_TOKEN ayarla veya terminalde bildirim cursor-auth çalıştır.")

    body, err = _get_usage_summary(token, auth_id)
    if body is None:
        parts = [
            f"Cursor limit API yanıt vermedi ({err}).",
            "Oturumu yenile: .venv/bin/python -m bildirim cursor-auth",
            "Dashboard: https://cursor.com/settings (Usage)",
            f"Auth kaynağı: {source}",
        ]
        return UsageSummary(ok=False, text="\n".join(parts))

    return UsageSummary(ok=True, text=_format_usage(body), raw=body)


def save_session_interactive() -> UsageSummary:
    """Store a session supplied by its owner for the optional usage command."""
    value = getpass.getpass("Cursor oturum anahtarı (gizli): ").strip()
    if not value:
        return UsageSummary(False, "Anahtar boş, kayıt yapılmadı.")
    path = session_token_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as tmp:
        tmp.write(value)
    os.replace(tmp.name, path)
    return UsageSummary(True, "Oturum kaydedildi. Kullanımı bildirim limit ile kontrol edebilirsin.")


def _resolve_access_token() -> tuple[str | None, str | None, str]:
    env_token = (os.environ.get("CURSOR_SESSION_TOKEN") or "").strip()
    if env_token:
        auth_id, token = _split_session_value(env_token)
        return token, auth_id, "env:CURSOR_SESSION_TOKEN"

    path = session_token_path()
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            auth_id, token = _split_session_value(raw)
            return token, auth_id, f"file:{path.name}"

    return None, None, "missing"


def _split_session_value(value: str) -> tuple[str | None, str]:
    token = value.strip()
    auth_id = None
    if "::" in token:
        auth_id, token = token.split("::", 1)
    elif "%3A%3A" in token:
        auth_id, token = urllib.parse.unquote(token).split("::", 1)
    return auth_id, token


def _get_usage_summary(
    token: str, auth_id: str | None
) -> tuple[dict[str, Any] | None, str]:
    cookie_values: list[str] = [token]
    if auth_id:
        cookie_values.append(f"{auth_id}::{token}")
        cookie_values.append(urllib.parse.quote(f"{auth_id}::{token}"))

    last_err = "unknown"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for cookie in cookie_values:
        for url in (
            "https://www.cursor.com/api/usage-summary",
            "https://cursor.com/api/usage-summary",
        ):
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Cookie": f"WorkosCursorSessionToken={cookie}",
            }
            for extra in ({}, {"Authorization": f"Bearer {token}"}):
                req = urllib.request.Request(url, headers={**headers, **extra})
                try:
                    with opener.open(req, timeout=20) as resp:
                        payload = json.loads(resp.read().decode("utf-8"))
                        if isinstance(payload, dict):
                            return payload, ""
                        last_err = "unexpected_json"
                except urllib.error.HTTPError as exc:
                    last_err = f"HTTP {exc.code}"
                except Exception as exc:  # noqa: BLE001
                    last_err = type(exc).__name__
    return None, last_err


def _format_usage(body: dict[str, Any]) -> str:
    membership = body.get("membershipType") or "?"
    auto = api = None
    iu = body.get("individualUsage")
    if isinstance(iu, dict):
        plan = iu.get("plan")
        if isinstance(plan, dict):
            auto = plan.get("autoPercentUsed")
            api = plan.get("apiPercentUsed")
    days = _days_until(body.get("billingCycleEnd"))
    lines = [
        f"Plan: {membership}",
        f"Auto: {_pct2(auto)}",
        f"API: {_pct2(api)}",
    ]
    if days is None:
        lines.append("Yenilenme: ?")
    elif days <= 0:
        lines.append("Yenilenme: bugün / geçmiş")
    elif days == 1:
        lines.append("Yenilenme: 1 gün sonra")
    else:
        lines.append(f"Yenilenme: {days} gün sonra")
    return "\n".join(lines)


def _pct2(value: Any) -> str:
    try:
        return f"%{float(value):.2f}"
    except (TypeError, ValueError):
        return "%?"


def _days_until(cycle_end: Any) -> int | None:
    if not cycle_end:
        return None
    from datetime import datetime, timezone

    raw = str(cycle_end).strip()
    try:
        if raw.isdigit():
            # ms epoch
            end = datetime.fromtimestamp(int(raw) / 1000.0, tz=timezone.utc)
        else:
            end = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return max(0, (end.date() - now.date()).days)
    except (TypeError, ValueError, OSError):
        return None
