# Use Cursor from Telegram

Cursor's user hooks post IDE events to a local authenticated bridge. The Mac bot opens one Telegram forum topic per top-level IDE agent session, named with the project and short session ID. If it cannot create a topic, it uses `TELEGRAM_TOPIC_MAC_M4`. CLI summary calls and IDE subagents do not open extra topics.

## Telegram commands

| Command | Effect |
| --- | --- |
| `/ping` | Check that the Mac bot is listening. |
| `/oturumlar` | List recent sessions with project name, short ID, and topic. |
| `/limit` | Request a Cursor usage summary. |
| `/dur`, `/devam` | Pause or resume a session. Use the session topic or supply its short ID. |
| `/dur hepsi`, `/devam hepsi` | Pause or resume all sessions, including new ones. |
| `/ozet` | Summarize the session in the current topic. You can also supply a short ID. |
| `/yaz merhaba` | Bring the session's Cursor window forward, enter the message, submit it, and restore the previous app. |
| `/ekran` | In Mac-M4, open the desktop panel. In a session topic, stream that Cursor window to Telegram. |
| `/ekran dur` | Stop sharing. |

Plain text in a session topic goes to a model with access to that session's traces and topic history. The Mac-M4 topic can work across sessions. An explicit `/yaz` sends a prompt directly to the IDE. A pause can block subsequent tool calls, shell commands, file reads, MCP actions, subagents, and new prompts. Use **Stop** in Cursor to interrupt an answer already being generated.

## Control the desktop

Send `/ekran` in Mac-M4 and open the HTTPS link on your phone. Tap the image to click, or use the touch menu for double-click, right-click, and drag. Keyboard and text controls target the focused field. For hands-free use, tap **Konuşmayı aç** (“start talking”) and allow microphone access. The Mac transcribes Turkish speech. Listening pauses during spoken replies. If Telegram's embedded browser restricts the microphone or playback, open the link in the phone's browser.

| Say this in Turkish | What happens |
| --- | --- |
| Ekranı sağa kaydır | Switch to the next macOS Space or full-screen app. |
| Sayfayı sağa kaydır | Scroll the current app horizontally. |
| Hangi uygulamalar açık? / Safari’ye geç | List open apps or bring Safari forward. |
| İmleci sağa 80 piksel taşı / çift tıkla / kopyala | Move the pointer, double-click, or copy. |
| Codex’e merhaba yaz | Draft a greeting in the current Codex chat. |
| Buraya merhaba yaz | Type into the selected field. |
| Teams’ten birine mesaj yaz | Ask for a Teams recipient and message. |
| Teams’ten Ayşe Yılmaz’a şunu yaz: Yarın görüşelim. | Prepare a draft for the named person. |

The Teams flow can request a work email to disambiguate recipients. A pending dialog waits up to 90 seconds and accepts “Vazgeç” (“cancel”). For a verified chat draft, “Gönder” (“send”) is a separate command. Screen questions use the configured Cursor/Grok provider. End the desktop session with `/ekran dur`. Its maximum duration is 15 minutes.

## Stream a single Cursor window

Start a Telegram group live stream and select **Stream with another app**. Save its destination and key in `TELEGRAM_RTMP_URL` and `TELEGRAM_RTMP_KEY`. Send `/ekran` in the Cursor session topic. Grant Screen Recording permission if macOS requests it, then try again. Use `/ekran dur` to stop the stream.

## Configuration and troubleshooting

- **Hooks and state.** Run `python scripts/install-hooks.py` from the checkout to register `scripts/bildirim-mirror.py` in `~/.cursor/hooks.json`. The default local port is 18765. The active port is recorded in `data/bridge.port`, and session metadata in `data/cursor_sessions.json`.
- **Chat and summaries.** Configure `CURSOR_API_KEY` and make `cursor-agent` available on your PATH. The integration selects an available Grok model and caches the selection for about an hour. Override it with `SEYIR_GROK_MODEL`. Topic history is kept in `data/topic_chats/`, and session traces in `data/cursor_traces/`.
- **Usage.** Set `CURSOR_SESSION_TOKEN` in your local environment or use the hidden prompt in `seyir cursor-auth`. The latter writes `data/cursor_session.token` with mode 0600. Run `seyir limit` to check. If the usage endpoint changes, check the Cursor account dashboard.
- **Background service.** Use `scripts/mac-m4-service.sh start`, `status`, or `stop`. The LaunchAgent is `local.bildirim.mac-m4`. Its standard output is written to `data/logs/mac-m4-bot.out.log`.
