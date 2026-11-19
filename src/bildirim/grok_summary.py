"""Summarize an IDE agent session with Grok (top model via cursor-agent / xAI)."""

from __future__ import annotations

import json
import os
import struct
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from bildirim.cursor_agent_cli import cursor_agent_ask, cursor_api_key
from bildirim.cursor_sessions import SessionStore
from bildirim.cursor_trace import evidence_text
from bildirim.cursor_usage import session_token_path
from bildirim.grok_model import FALLBACK_GROK_MODEL, resolve_top_grok
from bildirim.telegram_format import escape_html, to_telegram_html

DEFAULT_GROK_MODEL = FALLBACK_GROK_MODEL
XAI_MODEL = os.environ.get("GROK_MODEL", "grok-4").strip() or "grok-4"


@dataclass(frozen=True)
class SummaryResult:
    ok: bool
    text: str
    html: str


def summarize_session(
    store: SessionStore,
    *,
    conversation_id: str | None = None,
    short_or_arg: str = "",
) -> SummaryResult:
    cid, meta = _resolve_session(store, conversation_id, short_or_arg)
    if cid is None or meta is None:
        msg = "Özetlenecek oturum yok. /oturumlar ile id bakıp /ozet <id> yaz."
        return SummaryResult(ok=False, text=msg, html=escape_html(msg))

    evidence = evidence_text(cid, meta=meta)
    prompt = (
        "Aşağıda Cursor IDE agent oturumundan kısa izler var. "
        "Türkçe, kısa ve net bir durum özeti yaz.\n"
        "Tam olarak şu başlıkları kullan (her başlık tek satır, ardından 1-3 kısa madde):\n"
        "Şu an ne yapıyor\n"
        "Son adımlar\n"
        "Risk/blokaj\n"
        "Sırada ne olabilir\n"
        "Markdown, emoji, kod çiti kullanma. Madde başında • kullan. Abartma.\n\n"
        f"Oturum: {meta.get('short_id')} · {meta.get('project')}\n"
        f"İzler:\n{evidence}"
    )

    model = resolve_top_grok()
    raw, err = _call_grok(prompt, model=model)
    if not raw:
        msg = (
            f"Grok özeti alınamadı ({err}).\n"
            "CURSOR_API_KEY veya XAI_API_KEY .env içine ekle; cursor-agent kurulu olsun."
        )
        return SummaryResult(ok=False, text=msg, html=escape_html(msg))

    text = raw.strip()
    header = f"Özet · {meta.get('short_id')} · {meta.get('project') or '?'}\nModel: {model}\n\n"
    full = header + text
    return SummaryResult(
        ok=True,
        text=full,
        html=to_telegram_html(text, header=header.rstrip()),
    )


def _resolve_session(
    store: SessionStore,
    conversation_id: str | None,
    short_or_arg: str,
) -> tuple[str | None, dict[str, Any] | None]:
    store.reload()
    if conversation_id:
        meta = store.get(conversation_id)
        return (conversation_id, meta) if meta else (None, None)
    arg = (short_or_arg or "").strip()
    if arg:
        found = store.find_by_short(arg)
        if found:
            return found
    found = store.active()
    return found if found else (None, None)


def _call_grok(prompt: str, *, model: str) -> tuple[str | None, str]:
    last = "no_provider"

    # 1) cursor-agent ask mode with CURSOR_API_KEY (preferred; top Grok on Cursor)
    if cursor_api_key():
        text, err = cursor_agent_ask(prompt, model=model)
        if text:
            return text, ""
        last = err
    else:
        last = "no_cursor_api_key"

    # 2) Official xAI if key present
    xai = (os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY") or "").strip()
    if xai:
        text, err = _xai_chat(prompt, api_key=xai, model=XAI_MODEL)
        if text:
            return text, ""
        last = err

    # 3) Cursor session JWT → fragile Connect proto (last resort)
    token = _cursor_bearer()
    if token:
        text, err = _cursor_grok_chat(prompt, token=token, model=model)
        if text:
            return text, ""
        last = err or last
    return None, last


def _cursor_bearer() -> str | None:
    env = (os.environ.get("CURSOR_SESSION_TOKEN") or "").strip()
    if env:
        return env.split("::")[-1].split("%3A%3A")[-1]
    path = session_token_path()
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            return raw.split("::")[-1]
    return None


def _xai_chat(prompt: str, *, api_key: str, model: str) -> tuple[str | None, str]:
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Sen kısa durum özetleyicisisin. Türkçe yaz. Markdown kullanma.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices") or []
        if not choices:
            return None, "empty_choices"
        msg = (choices[0].get("message") or {}).get("content") or ""
        return (str(msg).strip() or None), "empty"
    except urllib.error.HTTPError as exc:
        return None, f"xai_HTTP_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return None, type(exc).__name__


def _cursor_grok_chat(prompt: str, *, token: str, model: str) -> tuple[str | None, str]:
    """Minimal Connect+proto StreamUnifiedChatWithTools call."""
    conversation_id = str(uuid.uuid4())
    # ConversationMessage: text=1, type=2 (1=human)
    human = _pb_string(1, prompt) + _pb_varint_field(2, 1)
    # ModelDetails: model_name=1
    model_details = _pb_string(1, model)
    # StreamUnifiedChatRequest-ish:
    # conversation=1, model_details=5, is_chat=22, conversation_id=23
    req_msg = (
        _pb_bytes(1, human)
        + _pb_bytes(5, model_details)
        + _pb_varint_field(22, 1)
        + _pb_string(23, conversation_id)
    )
    envelope = b"\x00" + struct.pack(">I", len(req_msg)) + req_msg

    url = "https://api2.cursor.sh/aiserver.v1.ChatService/StreamUnifiedChatWithTools"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/connect+proto",
        "Connect-Protocol-Version": "1",
        "Connect-Accept-Encoding": "identity",
        "User-Agent": "Mozilla/5.0",
        "x-cursor-client-version": "2.0.0",
        "x-cursor-client-type": "cli",
        "x-cursor-timezone": "Europe/Istanbul",
        "x-ghost-mode": "true",
        "x-request-id": str(uuid.uuid4()),
    }
    req = urllib.request.Request(url, data=envelope, headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=120) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:200]
        return None, f"cursor_HTTP_{exc.code}:{detail!r}"
    except Exception as exc:  # noqa: BLE001
        return None, type(exc).__name__

    text = _decode_connect_text(raw)
    if text:
        return text, ""
    return None, "cursor_empty_or_undecoded"


def _decode_connect_text(raw: bytes) -> str:
    """Pull UTF-8 strings from Connect envelopes / embedded JSON errors."""
    chunks: list[str] = []
    i = 0
    while i + 5 <= len(raw):
        flags = raw[i]
        length = struct.unpack(">I", raw[i + 1 : i + 5])[0]
        i += 5
        if length < 0 or i + length > len(raw):
            break
        payload = raw[i : i + length]
        i += length
        if flags == 2:
            # end stream / error JSON
            try:
                err = json.loads(payload.decode("utf-8", errors="replace"))
                if isinstance(err, dict) and err.get("error"):
                    return ""
            except json.JSONDecodeError:
                pass
            continue
        # Heuristic: extract readable protobuf strings
        chunks.extend(_extract_pb_strings(payload))
    # Prefer longer assistant-looking joins
    text = "\n".join(s for s in chunks if len(s) > 2)
    # Filter noise
    lines = [
        ln
        for ln in text.splitlines()
        if ln.strip()
        and not ln.strip().startswith("{")
        and "invalid_argument" not in ln
    ]
    return "\n".join(lines).strip()


def _extract_pb_strings(buf: bytes) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(buf):
        try:
            tag, ni = _read_varint(buf, i)
            i = ni
        except Exception:
            break
        field = tag >> 3
        wire = tag & 7
        if wire == 2:
            length, ni = _read_varint(buf, i)
            i = ni
            data = buf[i : i + length]
            i += length
            if field in {1, 2, 3, 15, 25} or length > 20:
                try:
                    s = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if _looks_like_text(s):
                    out.append(s)
        elif wire == 0:
            _, i = _read_varint(buf, i)
        elif wire == 5:
            i += 4
        elif wire == 1:
            i += 8
        else:
            break
    return out


def _looks_like_text(s: str) -> bool:
    if len(s) < 8:
        return False
    if sum(ch.isprintable() or ch in "\n\t" for ch in s) / len(s) < 0.85:
        return False
    # skip pure ids
    if all(ch.isalnum() or ch in "-_" for ch in s) and " " not in s:
        return False
    return True


def _pb_string(field: int, value: str) -> bytes:
    data = value.encode("utf-8")
    return _pb_tag(field, 2) + _pb_varint(len(data)) + data


def _pb_bytes(field: int, value: bytes) -> bytes:
    return _pb_tag(field, 2) + _pb_varint(len(value)) + value


def _pb_varint_field(field: int, value: int) -> bytes:
    return _pb_tag(field, 0) + _pb_varint(value)


def _pb_tag(field: int, wire: int) -> bytes:
    return _pb_varint((field << 3) | wire)


def _pb_varint(value: int) -> bytes:
    out = bytearray()
    v = int(value)
    while True:
        bits = v & 0x7F
        v >>= 7
        out.append(bits | (0x80 if v else 0))
        if not v:
            break
    return bytes(out)


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")
    raise ValueError("truncated varint")
