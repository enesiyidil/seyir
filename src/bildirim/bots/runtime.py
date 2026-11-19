"""Shared polling loop for the /ping stubs."""

from __future__ import annotations

from typing import Any


def require_ptb() -> Any:
    try:
        from telegram.ext import Application
    except ImportError:
        raise SystemExit(
            "python-telegram-bot kurulu değil.\n"
            "Proje klasöründe:\n"
            "  python3 -m venv .venv\n"
            "  source .venv/bin/activate\n"
            "  pip install -e ."
        ) from None
    return Application


def run_ping_bot(*, token: str, label: str, allowed_user_ids: tuple[int, ...]) -> None:
    application_type = require_ptb()
    from telegram import Update
    from telegram.ext import CommandHandler, ContextTypes

    if not allowed_user_ids:
        print(
            "Uyarı: TELEGRAM_ALLOWED_USER_IDS boş. /ping herkese açık.",
            flush=True,
        )

    async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or user.is_bot:
            return
        if allowed_user_ids and user.id not in allowed_user_ids:
            return
        await message.reply_text(f"pong ({label})")

    application = application_type.builder().token(token).build()
    application.add_handler(CommandHandler("ping", ping))
    print(f"{label} dinliyor. /ping yazın. Durdurmak için Ctrl+C.", flush=True)
    application.run_polling(drop_pending_updates=True, allowed_updates=["message"])
