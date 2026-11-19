"""Poll Apple Mail, classify, notify, mark read."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Callable

from bildirim.config import Settings, project_root
from bildirim.mail import applescript
from bildirim.mail.qwen import Classification, classify
from bildirim.mail.rules import MailItem, is_noise, looks_like_calendar
from bildirim.mail.store import ProcessedStore, default_path
from bildirim.mail.telegram_notify import send_alert


def process_once(settings: Settings, store: ProcessedStore, token: str) -> int:
    if settings.group_id is None or "mail" not in settings.topics:
        raise SystemExit("TELEGRAM_GROUP_ID ve TELEGRAM_TOPIC_MAIL gerekli.")
    handled = 0
    try:
        items = applescript.list_unread(limit=int(os.environ.get("MAIL_BATCH", "15")))
    except Exception as exc:  # noqa: BLE001 - surface Mail permission errors
        print(f"Mail okuma hatası: {exc}", flush=True)
        return 0

    for item in items:
        if not item.message_id:
            continue
        existing = store.get(item.message_id)
        if existing is not None:
            kind = str(existing.get("kind") or "")
            # Yarım kalan işler tekrar denensin; tamamlananlar atlanır.
            if kind not in {"pending", ""}:
                continue
            if existing.get("telegram_message_id"):
                continue
        handled += 1
        try:
            _handle_one(settings, store, token, item)
        except Exception as exc:  # noqa: BLE001
            print(f"Mail işlenemedi id={item.message_id}: {exc}", flush=True)
    return handled


def _handle_one(
    settings: Settings,
    store: ProcessedStore,
    token: str,
    item: MailItem,
) -> None:
    # Disk kaydı önce yazılır: Mac yeniden açılınca okunmamış kalsa bile tekrar işlenmez.
    if is_noise(item):
        applescript.mark_read(item.message_id)
        store.put(
            item.message_id,
            {
                "kind": "noise",
                "subject": item.subject,
                "sender": item.sender,
                "marked_read": True,
            },
        )
        print(f"noise → okundu: {item.subject[:80]}", flush=True)
        return

    store.put(
        item.message_id,
        {
            "kind": "pending",
            "subject": item.subject,
            "sender": item.sender,
            "body_preview": item.body[:4000],
            "marked_read": False,
        },
    )

    if looks_like_calendar(item):
        classification = classify(item)
        if classification.kind == "noise":
            classification = Classification(
                kind="meeting",
                subject=item.subject,
                when=item.date_received,
                participants="",
                reason="calendar_hint",
            )
    else:
        classification = classify(item)

    if classification.kind == "noise":
        applescript.mark_read(item.message_id)
        store.put(
            item.message_id,
            {
                "kind": "noise",
                "subject": item.subject,
                "sender": item.sender,
                "marked_read": True,
                "reason": classification.reason,
            },
        )
        print(f"qwen noise → okundu: {item.subject[:80]}", flush=True)
        return

    if classification.kind in {"meeting", "important"}:
        telegram_id = send_alert(
            settings, token=token, item=item, classification=classification
        )
        store.put(
            item.message_id,
            {
                "kind": classification.kind,
                "subject": classification.subject or item.subject,
                "sender": item.sender,
                "body_preview": item.body[:4000],
                "telegram_message_id": telegram_id,
                "marked_read": False,
                "when": classification.when,
                "participants": classification.participants,
                "reason": classification.reason,
            },
        )
        print(
            f"{classification.kind} → telegram/{telegram_id}: {item.subject[:80]}",
            flush=True,
        )
        return

    store.put(
        item.message_id,
        {
            "kind": "ignore",
            "subject": item.subject,
            "sender": item.sender,
            "marked_read": False,
            "reason": classification.reason,
        },
    )
    print(f"ignore: {item.subject[:80]}", flush=True)


async def poll_loop(settings: Settings, token: str, stop_event: asyncio.Event) -> None:
    store = ProcessedStore(default_path(project_root()))
    interval = int(os.environ.get("MAIL_POLL_SECONDS", "60"))
    print(f"Mail izleyici başladı. Aralık: {interval}s", flush=True)
    while not stop_event.is_set():
        await asyncio.to_thread(process_once, settings, store, token)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


def run_blocking(settings: Settings, token: str, should_stop: Callable[[], bool]) -> None:
    store = ProcessedStore(default_path(project_root()))
    interval = int(os.environ.get("MAIL_POLL_SECONDS", "60"))
    print(f"Mail izleyici başladı. Aralık: {interval}s", flush=True)
    while not should_stop():
        process_once(settings, store, token)
        time.sleep(interval)
