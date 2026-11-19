"""Mail bot: Telegram /ping + içerik isteği, Apple Mail izleyici."""

from __future__ import annotations

import asyncio
import re
import unicodedata

from bildirim.config import Settings, project_root
from bildirim.mail.store import ProcessedStore, default_path
from bildirim.mail.watcher import poll_loop

_CONTENT_WORDS = ("icerik", "content", "goster", "body", "govde")


def _normalize_tr(text: str) -> str:
    """Türkçe İ/I farkını sil; büyük harfli 'İçerik' de eşleşsin."""
    folded = (
        text.replace("İ", "i")
        .replace("I", "i")
        .replace("ı", "i")
        .replace("Ğ", "g")
        .replace("ğ", "g")
        .replace("Ü", "u")
        .replace("ü", "u")
        .replace("Ş", "s")
        .replace("ş", "s")
        .replace("Ö", "o")
        .replace("ö", "o")
        .replace("Ç", "c")
        .replace("ç", "c")
        .lower()
    )
    # 'İ'.lower() → 'i' + combining dot; temizle
    folded = unicodedata.normalize("NFKD", folded)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return folded.strip()


def _wants_content(text: str) -> bool:
    normalized = _normalize_tr(text)
    if not normalized:
        return False
    if normalized in _CONTENT_WORDS:
        return True
    # Kelime sınırı: "icerik?", "icerik lutfen", "mail icerigi" vb.
    return any(
        re.search(rf"(?<!\w){re.escape(word)}(?!\w)", normalized) for word in _CONTENT_WORDS
    )


def run(settings: Settings) -> None:
    settings.require_users()
    token = settings.token("mail")
    if settings.group_id is None or "mail" not in settings.topics:
        raise SystemExit(
            "Mail botu için TELEGRAM_GROUP_ID ve TELEGRAM_TOPIC_MAIL gerekli."
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
        raise SystemExit(
            "python-telegram-bot kurulu değil. pip install -e ."
        ) from exc

    store_path = default_path(project_root())

    def reload_store() -> ProcessedStore:
        # Diskten taze oku; süreç yeniden açılınca / yarım kalan kayıtlar görünsün.
        return ProcessedStore(store_path)

    async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot:
            return
        if not settings.permits(message.chat_id, user.id):
            return
        await message.reply_text("pong (mail)")

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot:
            return
        if not settings.permits(message.chat_id, user.id):
            print(
                f"içerik/metin yok sayıldı: user={user.id} allowlist dışı",
                flush=True,
            )
            return
        if message.message_thread_id != settings.topics["mail"]:
            return
        text = message.text or ""
        if not _wants_content(text):
            return

        store = reload_store()
        reply = message.reply_to_message
        record = None
        if reply is not None:
            record = store.find_by_telegram(reply.message_id)
            # Kullanıcı önceki "İçerik (...)" yanıtına tekrar yazarsa
            # yine aynı kayda düşebilmek için subject ipucu yoksa latest'e in.
        if record is None:
            # Yanıt bağlanmasa bile: her "içerik" isteğinde son alert gövdesi.
            record = store.latest_alert()

        print(
            f"içerik isteği user={user.id} text={text!r} "
            f"reply_to={getattr(reply, 'message_id', None)} "
            f"hit={bool(record)}",
            flush=True,
        )

        if record is None:
            await message.reply_text(
                'Önemli mail bildirimine yanıt verip "içerik" yaz, '
                "veya son önemli mail için yalnız içerik yaz."
            )
            return
        body = (record.get("body_preview") or "").strip()
        if not body:
            await message.reply_text("Kayıtlı içerik yok.")
            return
        # Her istekte yeniden gönder; kota / tek-seferlik yok.
        # PTB reply: forum konusunda kalır, HTTP reply_to hatalarına takılmaz.
        await message.reply_text(
            f"İçerik ({record.get('subject', '')}):\n\n{body[:3000]}"
        )

    async def post_init(application: Application) -> None:
        stop_event = asyncio.Event()
        application.bot_data["mail_stop"] = stop_event
        application.bot_data["mail_task"] = asyncio.create_task(
            poll_loop(settings, token, stop_event)
        )

    async def post_shutdown(application: Application) -> None:
        stop_event = application.bot_data.get("mail_stop")
        task = application.bot_data.get("mail_task")
        if isinstance(stop_event, asyncio.Event):
            stop_event.set()
        if asyncio.iscoroutine(task) or isinstance(task, asyncio.Task):
            try:
                await asyncio.wait_for(task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()

    application = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)
    )
    print(
        "Mail botu + izleyici ayakta. /ping ve önemli bildirime 'içerik' yanıtı.",
        flush=True,
    )
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message"],
    )
