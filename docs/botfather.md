# Connect the Telegram bots

1. In Telegram, open the official `@BotFather` chat and send `/newbot`. Choose a display name such as **Seyir Mail** or **Seyir Mac**. Each bot needs a unique username ending in `bot`.
2. Save the mail token as `TELEGRAM_BOT_TOKEN_MAIL` and the Mac token as `TELEGRAM_BOT_TOKEN_MAC_M4` in the local `.env` file. Set up only the roles you plan to run.
3. Add each bot to your private forum group. Make the Mac bot an administrator with permission to manage topics so it can open session topics and receive their messages. To ask the mail bot for content, reply directly to one of its alerts.
4. Run `seyir id-helper --role mail` or `seyir id-helper --role mac-m4`. Send `/id mail` or `/id mac-m4` in the corresponding topic. If several bots are present, address one explicitly, for example with `/id@your_bot_username mail`.
5. Save the reported group and topic IDs and the numeric Telegram IDs of allowed users. Stop the helper with Ctrl+C. Only one polling process should use a given bot token at a time.

If a token is exposed, revoke it through BotFather, update your local configuration, and restart the affected bot.
