"""Temporary helper: print group, topic, and user ids for .env."""

from __future__ import annotations

from bildirim.bots.runtime import require_ptb
from bildirim.config import TOPIC_ENV, Settings

ROLE_ALIASES: dict[str, str] = {
    "mail": "mail",
    "mac-m4": "mac-m4",
    "mac_m4": "mac-m4",
    "macm4": "mac-m4",
    "m4": "mac-m4",
    "mac-m1": "mac-m1",
    "mac_m1": "mac-m1",
    "macm1": "mac-m1",
    "m1": "mac-m1",
    "win11": "win11",
    "windows": "win11",
}


def format_id_report(
    *,
    chat_id: int | None,
    chat_type: str | None,
    topic_id: int | None,
    user_id: int | None,
    role_arg: str | None,
) -> str:
    warnings: list[str] = []
    body: list[str] = []
    role = ROLE_ALIASES.get(role_arg.lower()) if role_arg else None

    if role_arg and role is None:
        warnings.append(
            "Bilinmeyen konu. Kullanın: /id mail | /id mac-m4 | /id mac-m1 | /id win11"
        )
    if chat_type == "private":
        warnings.append(
            "Bu özel sohbet. Bildirim grubunu açın, konunun içine girin, komutu orada yazın."
        )
    elif chat_type == "group":
        warnings.append(
            "Konular kapalı görünüyor. Grup ayarından Konular'ı açın, sonra komutu konu içinde yazın."
        )
    elif topic_id is None and chat_type == "supergroup":
        warnings.append("topic_id yok. Komutu konunun içinde yazın, General dışında.")
    elif topic_id == 1:
        warnings.append(
            "topic_id 1 genellikle General konusudur. "
            "Mail, Mac-M4, Mac-M1 veya Win11 konusunu açıp komutu orada yazın."
        )

    if chat_type != "private" and chat_id is not None:
        body.append(f"TELEGRAM_GROUP_ID={chat_id}")
    if chat_type == "supergroup" and topic_id not in (None, 1):
        if role:
            body.append(f"{TOPIC_ENV[role]}={topic_id}")
        else:
            body.append(f"topic_id={topic_id}")
            if not role_arg:
                warnings.append(
                    "Konu anahtarını ekleyin: /id mail | /id mac-m4 | /id mac-m1 | /id win11"
                )
    if user_id is not None:
        body.append(f"TELEGRAM_ALLOWED_USER_IDS={user_id}")

    if not body and not warnings:
        return "Kimlik alınamadı. Komutu grup konusunun içinde tekrar yazın."
    if warnings:
        return "\n".join(warnings + ([""] if body else []) + body)
    return "\n".join(body)


def run(settings: Settings, role: str) -> None:
    token = settings.token(role)
    application_type = require_ptb()
    from telegram import Update
    from telegram.ext import CommandHandler, ContextTypes

    async def on_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat
        if message is None or user is None or user.is_bot:
            return
        role_arg = context.args[0] if context.args else None
        text = format_id_report(
            chat_id=chat.id if chat else None,
            chat_type=chat.type if chat else None,
            topic_id=message.message_thread_id,
            user_id=user.id,
            role_arg=role_arg,
        )
        print(text, flush=True)
        print("---", flush=True)
        await message.reply_text(text)

    async def on_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        if message is None:
            return
        await message.reply_text(
            "id-helper ayakta. Konu içinde: /id mail | /id mac-m4 | /id mac-m1 | /id win11"
        )

    application = application_type.builder().token(token).build()
    application.add_handler(CommandHandler("id", on_id))
    application.add_handler(CommandHandler("ping", on_ping))
    print(
        f"id-helper ayakta. Dinleyen bot: {role}.\n"
        "Her konunun içinde bu bota yazın:\n"
        "  /id mail\n"
        "  /id mac-m4\n"
        "  /id mac-m1\n"
        "  /id win11\n"
        "Çıktıyı .env dosyasına yapıştırın. Bitince Ctrl+C.",
        flush=True,
    )
    application.run_polling(drop_pending_updates=True, allowed_updates=["message"])
