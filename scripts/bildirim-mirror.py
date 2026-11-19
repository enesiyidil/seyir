#!/usr/bin/env python3
"""Cursor hook → local Seyir mac-m4 bridge (IDE mirror + hard-ish stop)."""

from __future__ import annotations

import json
import sys
import urllib.request

from bildirim.config import bridge_secret, load_settings, project_root, project_setting

ROOT = project_root()
PORT_FILE = ROOT / "data" / "bridge.port"
STOPS_DIR = ROOT / "data" / "cursor_stops"
FREEZE_FILE = ROOT / "data" / "cursor_freeze_all"
DEFAULT_PORT = 18765

DENY_EVENTS = {
    "preToolUse",
    "beforeSubmitPrompt",
    "beforeShellExecution",
    "beforeMCPExecution",
    "subagentStart",
    "beforeReadFile",
}


def bridge_url() -> str:
    port = DEFAULT_PORT
    if PORT_FILE.is_file():
        try:
            port = int(PORT_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            pass
    env_port = project_setting("BRIDGE_PORT")
    if env_port:
        try:
            port = int(env_port)
        except ValueError:
            pass
    return f"http://127.0.0.1:{port}/hook"


def _safe_id(conversation_id: str) -> str:
    return "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in conversation_id
    )[:120]


def local_should_block(conversation_id: str, parent_id: str) -> bool:
    if FREEZE_FILE.is_file():
        return True
    for cid in (conversation_id, parent_id):
        if not cid:
            continue
        if (STOPS_DIR / _safe_id(cid)).is_file():
            return True
    return False


def post_hook(payload: dict) -> dict:
    load_settings()
    secret = bridge_secret()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Bildirim-Secret"] = secret
    req = urllib.request.Request(
        bridge_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body if isinstance(body, dict) else {}
    except Exception as exc:  # noqa: BLE001
        print(f"Seyir bridge error: {exc}", file=sys.stderr)
        return {"ok": False, "deny": False}


def emit_deny(event: str, message: str) -> None:
    if event == "beforeSubmitPrompt":
        print(json.dumps({"continue": False, "user_message": message}))
        return
    if event == "stop":
        print("{}")
        return
    # permission-style hooks
    print(
        json.dumps(
            {
                "permission": "deny",
                "user_message": message,
                "agent_message": message,
            }
        )
    )


def emit_allow(event: str) -> None:
    if event == "beforeSubmitPrompt":
        print(json.dumps({"continue": True}))
        return
    if event in DENY_EVENTS:
        print(json.dumps({"permission": "allow"}))
        return
    print("{}")


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    event = str(payload.get("hook_event_name") or "")
    conversation_id = str(
        payload.get("conversation_id") or payload.get("session_id") or ""
    ).strip()
    parent_id = str(payload.get("parent_conversation_id") or "").strip()

    # Dosya bayrağı: bridge kapalı olsa bile durdurma çalışsın.
    local_deny = local_should_block(conversation_id, parent_id)
    result = post_hook(payload)
    deny = local_deny or bool(result.get("deny"))
    message = str(
        result.get("message")
        or "Seyir /dur — oturum kilitli (tool/shell/MCP/alt-ajan kapalı)."
    )

    if event == "stop" and (local_deny or result.get("block_followup")):
        # Auto follow-up yok
        print("{}")
        return 0

    if event in DENY_EVENTS:
        if deny:
            emit_deny(event, message)
        else:
            emit_allow(event)
        return 0

    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
