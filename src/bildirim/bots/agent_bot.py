"""PC agent bot: IDE mirror bridge + /ping /oturumlar /limit /dur (mac-m4)."""

from __future__ import annotations

import asyncio
import json
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bildirim.bots.runtime import run_ping_bot
from bildirim.config import AGENT_ROLES, Settings, bridge_secret, project_root, project_setting
from bildirim.cursor_agent_cli import (
    GROK_SENTINEL,
    cli_spawn_active,
    is_cli_session,
    remember_cli_session,
)
from bildirim.cursor_sessions import SessionStore
from bildirim.cursor_trace import append_event
from bildirim.cursor_usage import fetch_usage_summary
from bildirim.grok_chat import handle_topic_message
from bildirim.grok_summary import summarize_session
from bildirim.ide_send import send_to_ide
from bildirim.ide_stream import (
    arm_watch,
    mark_window_ended,
    mark_window_live,
    request_speech,
    start_stream,
    stop_stream,
)
from bildirim.voice_control import handle_spoken, result_html, transcribe_file
from bildirim.telegram_api import create_forum_topic, send_message

DEFAULT_BRIDGE_PORT = 18765
MAX_TEXT = 3500


def run(settings: Settings, role: str) -> None:
    settings.require_users()
    if role not in AGENT_ROLES:
        names = ", ".join(AGENT_ROLES)
        raise SystemExit(f"Bilinmeyen role: {role}. Seçenekler: {names}")

    if role != "mac-m4":
        run_ping_bot(
            token=settings.token(role),
            label=role,
            allowed_user_ids=settings.allowed_user_ids,
        )
        return

    _run_mac_m4(settings)


def _run_mac_m4(settings: Settings) -> None:
    token = settings.token("mac-m4")
    if settings.group_id is None:
        raise SystemExit("TELEGRAM_GROUP_ID gerekli.")
    fallback_topic = settings.topics.get("mac-m4")
    if fallback_topic is None:
        raise SystemExit("TELEGRAM_TOPIC_MAC_M4 gerekli (fallback konu).")

    store = SessionStore()
    bridge_port = int(project_setting("BRIDGE_PORT", str(DEFAULT_BRIDGE_PORT)))

    mirror = MirrorService(
        settings=settings,
        token=token,
        store=store,
        fallback_topic=fallback_topic,
    )

    server = _start_bridge(mirror, store, bridge_port, bridge_secret())
    print(
        f"mac-m4 mirror bridge http://127.0.0.1:{bridge_port}/hook",
        flush=True,
    )

    try:
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError as exc:
        server.shutdown()
        raise SystemExit("python-telegram-bot kurulu değil. pip install -e .") from exc

    def _ozet_arg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        if context.args:
            return context.args[0].strip()
        text = (update.effective_message.text or "").strip() if update.effective_message else ""
        parts = text.split(maxsplit=1)
        if len(parts) >= 2:
            return parts[1].split()[0].strip()
        return ""

    async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        await message.reply_text("pong (mac-m4) · mirror+limit+dur")

    async def oturumlar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        store.reload()
        rows = store.list_recent(12)
        if not rows:
            await message.reply_text("Kayıtlı IDE oturumu yok.")
            return
        lines = ["Son IDE oturumları:"]
        for cid, meta in rows:
            flag = "STOP" if meta.get("stop_requested") else ("aktif" if meta.get("active", True) else "bitti")
            lines.append(
                f"· {meta.get('short_id')} [{flag}] "
                f"{meta.get('project') or '?'} · topic={meta.get('topic_id')} "
                f"· {str(meta.get('last_at') or '')[:19]}"
            )
        await message.reply_text("\n".join(lines)[:3900])

    async def limit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        await message.reply_text("Limit sorgulanıyor…")
        summary = await asyncio.to_thread(fetch_usage_summary)
        await message.reply_text(summary.text[:3900])

    async def dur(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        store.reload()
        arg = (context.args[0].strip().lower() if context.args else "")

        if arg in {"hepsi", "all", "*"}:
            stopped = store.stop_all_active()
            await message.reply_text(
                "Durdurma: TÜM oturumlar + yeni işler kilitlendi.\n"
                f"İşaretlenen: {len(stopped)}\n"
                "Tool / shell / MCP / alt-ajan / yeni prompt engellenir.\n"
                "Şu an akan model cevabı için IDE’de Stop’a bas.\n"
                "Açmak için: /devam hepsi"
            )
            return

        cid: str | None = None
        meta: dict[str, Any] | None = None

        if arg:
            found = store.find_by_short(arg)
            if found:
                cid, meta = found
        if cid is None and message.message_thread_id is not None:
            found = store.find_by_topic(int(message.message_thread_id))
            if found:
                cid, meta = found
        if cid is None:
            found = store.active()
            if found:
                cid, meta = found

        if cid is None or meta is None:
            await message.reply_text(
                "Durdurulacak oturum yok.\n"
                "/oturumlar → /dur <id>\n"
                "veya her şey için: /dur hepsi"
            )
            return

        store.set_stop(cid, True)
        short = meta.get("short_id") or cid[:8]
        await message.reply_text(
            f"Durduruldu: {short}\n"
            "Bu oturumda tool / shell / MCP / alt-ajan / yeni prompt engelli.\n"
            "Akan cevap varsa IDE Stop’a bas.\n"
            "Tekrar açmak: /devam"
        )
        try:
            topic = meta.get("topic_id") or fallback_topic
            send_message(
                token,
                chat_id=settings.group_id,  # type: ignore[arg-type]
                message_thread_id=int(topic) if topic else fallback_topic,
                text=f"⏹ Durduruldu: {short}",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"dur notify failed: {exc}", flush=True)

    async def ozet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        store.reload()
        arg = _ozet_arg(update, context)
        cid: str | None = None
        if arg:
            found = store.find_by_short(arg)
            if found:
                cid = found[0]
        if cid is None and message.message_thread_id is not None:
            found = store.find_by_topic(int(message.message_thread_id))
            if found:
                cid = found[0]
        await message.reply_text("Grok özetliyor… (~20–40 sn)")
        result = await asyncio.to_thread(
            summarize_session, store, conversation_id=cid, short_or_arg=arg
        )
        # Telegram HTML; parse hatasında düz metin
        try:
            await message.reply_text(result.html, parse_mode="HTML")
        except Exception:  # noqa: BLE001
            await message.reply_text(result.text[:3900])

    async def ozet_tr_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Telegram ASCII komut zorunlu; /özet metin olarak gelsin diye."""
        message = update.effective_message
        if message is None or not message.text:
            return
        raw = message.text.strip()
        low = raw.casefold()
        if not (low.startswith("/özet") or low.startswith("özet")):
            return
        await ozet(update, context)

    async def topic_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Non-slash messages → Grok chat (meta or session topic)."""
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        text = (message.text or "").strip()
        if not text:
            return
        # Slash → never chat (commands own that path; unknown /x ignored)
        if text.startswith("/"):
            return
        # bare "özet" handled elsewhere
        if text.casefold().startswith("özet"):
            return
        thread_id = message.message_thread_id
        if thread_id is None:
            return

        store.reload()
        mode: str | None = None
        cid: str | None = None
        if int(thread_id) == int(fallback_topic):
            mode = "meta"
        else:
            found = store.find_by_topic(int(thread_id))
            if found:
                cid, _meta = found
                mode = "session"
        if mode is None:
            return

        if text.casefold().strip(" .!") in {"ekran aç", "ekranı aç", "ekran paylaşımı aç", "ekran paylaşımını aç"}:
            await ekran(update, context)
            return

        await message.reply_text("Grok düşünüyor… (~20–40 sn)")
        result = await asyncio.to_thread(
            handle_topic_message,
            store,
            topic_id=int(thread_id),
            user_text=text,
            mode=mode,
            conversation_id=cid,
        )
        try:
            await message.reply_text(result.html, parse_mode="HTML")
        except Exception:  # noqa: BLE001
            await message.reply_text(result.text[:3900])

    async def devam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        store.reload()
        arg = (context.args[0].strip().lower() if context.args else "")
        if arg in {"hepsi", "all", "*"} or store.is_freeze_all():
            store.set_freeze_all(False)
            # Clear stop flags on recent sessions
            for cid, _meta in store.list_recent(50):
                store.clear_stop(cid)
            await message.reply_text("Devam: tüm kilit kaldırıldı.")
            return

        cid: str | None = None
        meta: dict[str, Any] | None = None
        if arg:
            found = store.find_by_short(arg)
            if found:
                cid, meta = found
        if cid is None and message.message_thread_id is not None:
            found = store.find_by_topic(int(message.message_thread_id))
            if found:
                cid, meta = found
        if cid is None:
            found = store.active()
            if found:
                cid, meta = found
        if cid is None or meta is None:
            await message.reply_text("Açılacak oturum yok. /devam hepsi veya /devam <id>")
            return
        store.clear_stop(cid)
        short = meta.get("short_id") or cid[:8]
        await message.reply_text(f"Devam: {short} kilidi kalktı.")

    def _thread_project(message: Any) -> tuple[str, str]:
        """Return (project, note) for the topic, or active session."""
        store.reload()
        thread = message.message_thread_id
        if thread is not None and int(thread) != int(fallback_topic):
            found = store.find_by_topic(int(thread))
            if found:
                _cid, meta = found
                return str(meta.get("project") or ""), str(meta.get("short_id") or "")
        found = store.active()
        if found:
            _cid, meta = found
            return str(meta.get("project") or ""), str(meta.get("short_id") or "")
        return "", ""

    async def yaz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        raw = " ".join(context.args).strip() if context.args else ""
        if not raw and message.text:
            parts = message.text.split(maxsplit=1)
            raw = parts[1].strip() if len(parts) > 1 else ""
        if not raw:
            await message.reply_text("Kullanım: /yaz <metin>\nIDE agent kutusuna yazar ve Enter’a basar.")
            return
        project, short = _thread_project(message)
        await message.reply_text("IDE’ye yazılıyor…")
        result = await asyncio.to_thread(send_to_ide, raw, project=project)
        extra = f" ({short})" if short else ""
        await message.reply_text((result.text + extra)[:3900])

    async def ekran(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        arg = (context.args[0].strip().lower() if context.args else "")
        if arg in {"dur", "stop", "bitir", "kapat"}:
            result = await asyncio.to_thread(stop_stream)
            await message.reply_text(result.text[:3900])
            return
        thread = message.message_thread_id
        desktop = thread is not None and int(thread) == int(fallback_topic)
        project, short = ("", "") if desktop else _thread_project(message)
        cid = ""
        if not desktop and thread is not None:
            found = store.find_by_topic(int(thread))
            if found:
                cid = found[0]
                project = str(found[1].get("project") or project)
                short = str(found[1].get("short_id") or short)
        await message.reply_text(
            "Mac ekranı ve sohbet hazırlanıyor…" if desktop else "Bu pencere yayınlanıyor…"
        )
        result = await asyncio.to_thread(
            start_stream,
            project=project,
            mode="desktop" if desktop else "window",
            topic_id=int(thread) if thread is not None else None,
            conversation_id=cid,
            short_id=short,
        )
        await message.reply_text(result.text[:3900], disable_web_page_preview=True)

    async def on_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        file_id = ""
        suffix = ".jpg"
        if message.photo:
            file_id = message.photo[-1].file_id
        elif message.document and str(message.document.mime_type or "").startswith("image/"):
            file_id = message.document.file_id
            suffix = Path(message.document.file_name or "img.jpg").suffix or ".jpg"
        if not file_id:
            return
        caption = (message.caption or "").strip() or "Bu görüntüdeki sorunu incele."
        folder = project_root() / "data" / "inbox"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{message.message_id}{suffix}"
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(str(dest))
        thread_id = message.message_thread_id
        mode = "meta"
        cid: str | None = None
        if thread_id is not None and int(thread_id) != int(fallback_topic):
            found = store.find_by_topic(int(thread_id))
            if found:
                cid = found[0]
                mode = "session"
            else:
                return
        await message.reply_text("Görüntüyü inceliyorum…")
        result = await asyncio.to_thread(
            handle_topic_message,
            store,
            topic_id=int(thread_id or 0),
            user_text=caption,
            mode=mode,
            conversation_id=cid,
            image_path=str(dest),
        )
        try:
            await message.reply_text(result.html, parse_mode="HTML")
        except Exception:
            await message.reply_text(result.text[:3900])

    async def voice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot or not settings.permits(message.chat_id, user.id):
            return
        voice = message.voice or message.audio
        if voice is None:
            return
        await message.reply_text("Dinliyorum…")
        folder = project_root() / "data"
        folder.mkdir(parents=True, exist_ok=True)
        src = folder / "voice-in.ogg"
        tg_file = await context.bot.get_file(voice.file_id)
        await tg_file.download_to_drive(str(src))
        spoken, err = await asyncio.to_thread(transcribe_file, src)
        if not spoken:
            await message.reply_text(err[:500] or "Ses anlaşılamadı.")
            return
        result = await asyncio.to_thread(handle_spoken, spoken)
        try:
            await message.reply_text(result_html(f"Ses: {spoken}\n{result}"), parse_mode="HTML")
        except Exception:
            await message.reply_text(f"Ses: {spoken}\n{result}"[:3900])

    async def on_video_chat_started(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        if message is None or message.chat_id != settings.group_id or message.video_chat_started is None:
            return
        mark_window_live()
        request_speech("Bu pencere yayında.")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("oturumlar", oturumlar))
    application.add_handler(CommandHandler("limit", limit_cmd))
    application.add_handler(CommandHandler("dur", dur))
    application.add_handler(CommandHandler("devam", devam))
    application.add_handler(CommandHandler("ozet", ozet))
    application.add_handler(CommandHandler("yaz", yaz))
    application.add_handler(CommandHandler("ekran", ekran))
    async def on_video_chat_ended(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        if message is None or message.chat_id != settings.group_id or message.video_chat_ended is None:
            return
        await asyncio.to_thread(mark_window_ended)

    application.add_handler(
        MessageHandler(filters.StatusUpdate.VIDEO_CHAT_STARTED, on_video_chat_started)
    )
    application.add_handler(
        MessageHandler(filters.StatusUpdate.VIDEO_CHAT_ENDED, on_video_chat_ended)
    )
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_cmd))
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_image)
    )
    # /özet (Türkçe ö) — komut değil
    application.add_handler(
        MessageHandler(
            filters.Regex(r"(?i)^/özet(@\w+)?(\s|$)") | filters.Regex(r"(?i)^özet(\s|$)"),
            ozet_tr_text,
        ),
        group=0,
    )
    # Düz metin sohbet ( / ile başlayanlar sohbete gitmez )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, topic_chat),
        group=1,
    )

    print(
        "mac-m4 dinliyor: /komutlar + konu sohbeti (Grok) · IDE mirror",
        flush=True,
    )
    arm_watch()
    try:
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=["message"],
        )
    finally:
        server.shutdown()


class MirrorService:
    def __init__(
        self,
        *,
        settings: Settings,
        token: str,
        store: SessionStore,
        fallback_topic: int,
    ) -> None:
        self.settings = settings
        self.token = token
        self.store = store
        self.fallback_topic = fallback_topic
        self._lock = threading.Lock()

    def _should_skip_mirror(
        self,
        event: str,
        conversation_id: str,
        parent_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """CLI Grok turns and IDE subagents must not open a Telegram topic."""
        prompt = str(payload.get("prompt") or payload.get("text") or "")
        if GROK_SENTINEL in prompt and conversation_id:
            remember_cli_session(conversation_id)
            return True
        if conversation_id and is_cli_session(conversation_id):
            return True
        if parent_id and is_cli_session(parent_id):
            if conversation_id:
                remember_cli_session(conversation_id)
            return True
        if parent_id:
            hint = str(
                payload.get("tool_name")
                or payload.get("prompt")
                or payload.get("text")
                or event
            )[:240]
            append_event(parent_id, "subagent", f"{event}: {hint}")
            return True
        # Grok CLI opens with sessionStart before the prompt. Don't make a topic
        # yet; the prompt either carries the sentinel or is a real IDE message.
        if event == "sessionStart" and cli_spawn_active():
            return True
        return False

    def handle_hook(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = str(
            payload.get("hook_event_name")
            or payload.get("event")
            or ""
        )
        conversation_id = str(
            payload.get("conversation_id")
            or payload.get("session_id")
            or ""
        ).strip()
        parent_id = str(payload.get("parent_conversation_id") or "").strip()

        block_events = {
            "preToolUse",
            "beforeSubmitPrompt",
            "beforeShellExecution",
            "beforeMCPExecution",
            "subagentStart",
            "beforeReadFile",
        }
        if event in block_events:
            if self.store.should_block(conversation_id, parent_id):
                return {
                    "ok": True,
                    "deny": True,
                    "message": "Seyir /dur — oturum kilitli (tool/shell/MCP/alt-ajan kapalı).",
                }

        # stop hook: auto-followup üretme
        if event == "stop" and self.store.should_block(conversation_id, parent_id):
            return {
                "ok": True,
                "deny": False,
                "block_followup": True,
                "message": "Seyir /dur — follow-up yok.",
            }

        if not conversation_id and event not in {"", "ping"}:
            return {"ok": True, "deny": False}

        if self._should_skip_mirror(event, conversation_id, parent_id, payload):
            return {"ok": True, "deny": False}

        try:
            if event == "sessionStart":
                # Global freeze varken yeni oturum açılsa bile hemen kilitle
                if self.store.is_freeze_all() and conversation_id:
                    self.store.set_stop(conversation_id, True)
                self._on_session_start(payload, conversation_id)
            elif event == "beforeSubmitPrompt":
                self._on_prompt(payload, conversation_id)
            elif event == "afterAgentResponse":
                self._on_response(payload, conversation_id)
            elif event == "postToolUse":
                self._on_tool(payload, conversation_id)
            elif event == "stop":
                self._on_stop(payload, conversation_id)
            elif event == "sessionEnd":
                if conversation_id:
                    self.store.mark_ended(conversation_id)
        except Exception as exc:  # noqa: BLE001
            print(f"mirror handle error event={event}: {exc}", flush=True)
            return {"ok": False, "deny": False, "error": str(exc)[:200]}

        return {"ok": True, "deny": False}

    def _project_name(self, payload: dict[str, Any]) -> str:
        roots = payload.get("workspace_roots") or payload.get("workspaceRoots") or []
        if isinstance(roots, list) and roots:
            return Path(str(roots[0])).name
        cwd = payload.get("cwd") or ""
        if cwd:
            return Path(str(cwd)).name
        return "cursor"

    def _ensure_session(self, conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.store.get(conversation_id)
        if existing and existing.get("topic_id"):
            return existing

        project = self._project_name(payload)
        short = conversation_id[:8] if conversation_id else "unknown"
        title = f"{project} · {short}"
        topic_id = self.fallback_topic
        # Network outside store locks — avoid blocking other hook requests.
        try:
            with self._lock:
                # Double-check after waiting for lock.
                existing = self.store.get(conversation_id)
                if existing and existing.get("topic_id"):
                    return existing
            topic_id = create_forum_topic(
                self.token,
                chat_id=self.settings.group_id,  # type: ignore[arg-type]
                name=title,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"createForumTopic failed, fallback topic: {exc}", flush=True)
            topic_id = self.fallback_topic

        return self.store.upsert(
            conversation_id,
            short_id=short,
            topic_id=topic_id,
            title=title,
            project=project,
            active=True,
        )

    def _topic(self, meta: dict[str, Any]) -> int:
        tid = meta.get("topic_id")
        return int(tid) if tid else self.fallback_topic

    def _send(self, meta: dict[str, Any], text: str) -> None:
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                send_message(
                    self.token,
                    chat_id=self.settings.group_id,  # type: ignore[arg-type]
                    message_thread_id=self._topic(meta),
                    text=text,
                )
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt == 0:
                    continue
        raise RuntimeError(f"telegram send failed: {last_exc}")

    def _on_session_start(self, payload: dict[str, Any], conversation_id: str) -> None:
        if not conversation_id:
            return
        meta = self._ensure_session(conversation_id, payload)
        model = payload.get("model") or "?"
        bg = payload.get("is_background_agent")
        append_event(
            conversation_id,
            "sessionStart",
            f"model={model} background={bg}",
            model=str(model),
        )
        self._send(
            meta,
            f"▶️ IDE oturum başladı\n"
            f"id: {meta.get('short_id')}\n"
            f"proje: {meta.get('project')}\n"
            f"model: {model}\n"
            f"background: {bg}",
        )

    def _on_prompt(self, payload: dict[str, Any], conversation_id: str) -> None:
        if not conversation_id:
            return
        meta = self._ensure_session(conversation_id, payload)
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            return
        append_event(conversation_id, "user", prompt)
        self._send(meta, f"👤 Sen:\n{_clip(prompt)}")

    def _on_response(self, payload: dict[str, Any], conversation_id: str) -> None:
        if not conversation_id:
            return
        meta = self._ensure_session(conversation_id, payload)
        text = str(payload.get("text") or "").strip()
        if not text:
            return
        append_event(conversation_id, "agent", text)
        self._send(meta, f"🤖 Agent:\n{_clip(text)}")

    def _on_tool(self, payload: dict[str, Any], conversation_id: str) -> None:
        if not conversation_id:
            return
        name = str(
            payload.get("tool_name")
            or payload.get("toolName")
            or payload.get("name")
            or "tool"
        )
        # Keep short: tool name + truncated input hint
        hint = str(
            payload.get("tool_input")
            or payload.get("input")
            or payload.get("arguments")
            or ""
        )[:240]
        append_event(conversation_id, "tool", f"{name} {hint}".strip(), tool=name)
        # Don't spam Telegram with every tool; traces feed /ozet.

    def _on_stop(self, payload: dict[str, Any], conversation_id: str) -> None:
        if not conversation_id:
            return
        meta = self.store.get(conversation_id) or self._ensure_session(
            conversation_id, payload
        )
        status = payload.get("status") or "?"
        loop_count = payload.get("loop_count")
        stop_flag = " · kilitli" if meta.get("stop_requested") else ""
        append_event(
            conversation_id,
            "stop",
            f"status={status} loop={loop_count}",
            status=str(status),
        )
        self._send(
            meta,
            f"⏹ Tur bitti: {status}"
            + (f" (loop={loop_count})" if loop_count is not None else "")
            + stop_flag,
        )


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n… (kesildi)"


def _start_bridge(
    mirror: MirrorService,
    store: SessionStore,
    port: int,
    secret: str,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"bridge {self.address_string()} {fmt % args}", flush=True)

        def _auth_ok(self) -> bool:
            header = self.headers.get("X-Bildirim-Secret") or ""
            return bool(secret) and secrets.compare_digest(header.encode(), secret.encode())

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def _write(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            try:
                self.wfile.flush()
            except Exception:  # noqa: BLE001
                pass

        def do_GET(self) -> None:  # noqa: N802
            if not self._auth_ok():
                self._write(401, {"ok": False, "error": "unauthorized"})
                return
            path = urlparse(self.path).path
            if path == "/health":
                from bildirim.desktop_control import desktop_permissions

                health = {"ok": True, "service": "bildirim-mac-m4", "permissions": desktop_permissions()}
                if urlparse(self.path).query == "voice=1":
                    from bildirim.voice_input import native
                    try:
                        health["voice"] = native(op="readiness")
                    except (OSError, ValueError, subprocess.SubprocessError):
                        health["voice"] = {"error": "Girdi yardımcısı yanıt vermedi."}
                self._write(200, health)
                return
            if path == "/stop-check":
                from urllib.parse import parse_qs

                qs = parse_qs(urlparse(self.path).query)
                cid = (qs.get("conversation_id") or [""])[0]
                store.reload()
                self._write(
                    200,
                    {
                        "ok": True,
                        "deny": store.is_stop_requested(cid) if cid else False,
                    },
                )
                return
            self._write(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._auth_ok():
                self._write(401, {"ok": False, "error": "unauthorized"})
                return
            path = urlparse(self.path).path
            if path != "/hook":
                self._write(404, {"ok": False, "error": "not_found"})
                return
            payload = self._read_json()
            result = mirror.handle_hook(payload)
            self._write(200, result)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, name="bildirim-bridge", daemon=True)
    thread.start()

    # Persist port for hooks
    port_file = project_root() / "data" / "bridge.port"
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(str(port), encoding="utf-8")
    return server
