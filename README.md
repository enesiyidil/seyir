# Seyir

English · [Türkçe](README.tr.md)

Seyir brings Apple Mail and Cursor agent sessions into a private Telegram group. A local Qwen model picks out important mail. Each Cursor session gets its own topic, where you can follow the conversation and send a message back to the IDE. When you need the desktop, open a temporary screen-sharing link on your phone to use the mouse, type, or speak Turkish commands.

| Telegram topic | What you can do |
| --- | --- |
| **Mail** | See meeting details and important messages. Reply to an alert with `içerik` to read a preview of the message body. |
| **Cursor session** | Ask for a summary with `/ozet`, send a prompt to that session with `/yaz`, or pause subsequent tool calls with `/dur`. |
| **Mac-M4** | List sessions with `/oturumlar`. Open the desktop panel with `/ekran` and close it with `/ekran dur`. |

The desktop assistant speaks Turkish. For example, *“Ekranı sağa kaydır”* moves to the next macOS Space, and *“Sayfayı sağa kaydır”* scrolls the current page horizontally. *“Codex’e merhaba yaz”* drafts a greeting in Codex. The Telegram command `/yaz merhaba` sends that greeting to the Cursor agent in the current topic.

## Install

Use a logged-in macOS desktop session and Python 3.11 or later. You can run the mail bot, the Mac bot, or both.

```sh
git clone https://github.com/enesiyidil/seyir.git
cd seyir
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp -n .env.example .env
chmod 600 .env
seyir --help
```

1. Create a private Telegram group with topics enabled. Create a separate bot for each role you plan to run. Save its token in `.env`, add it to the group, and grant the Mac bot permission to manage topics. [Telegram setup](docs/botfather.md)
2. Run `seyir id-helper --role mail` or `seyir id-helper --role mac-m4`. In the corresponding Telegram topic, send `/id mail` or `/id mac-m4`. Copy the reported group, topic, and allowed user IDs into `.env`. Stop the helper with Ctrl+C.
3. Start your chosen bot in a terminal for the first run so you can see permission prompts and configuration errors.

### Apple Mail and local Qwen

Sync your account in Apple Mail. Set `MAIL_ACCOUNT` and `MAIL_INBOX` to the names shown in Mail. Set `MAIL_INTERNAL_DOMAINS` to a comma-separated list of your organization's domains. Start your local oMLX server and set `OMLX_BASE_URL` and `OMLX_MODEL` to match. Seyir reads the API key from `OMLX_API_KEY` or your local oMLX settings.

```sh
seyir mail
```

The first scan processes your actual inbox. Messages classified as noise are **marked as read**. Meetings and important messages stay unread. [Mail classification rules](docs/mail-rules.md)

### Cursor and desktop control

Install Cursor and the Apple Command Line Tools. The desktop panel uses `cloudflared` for HTTPS and `ffmpeg` for audio and window streaming. With Homebrew, run `brew install cloudflared ffmpeg`. For screen questions, topic conversations, and summaries, configure the Cursor CLI (`cursor-agent`) and `CURSOR_API_KEY`.

```sh
python scripts/install-hooks.py
seyir agent --role mac-m4
```

The installer adds events to your existing Cursor hooks and generates a local bridge secret. Reopen Cursor and start an agent chat. Grant Screen Recording, Accessibility, Automation, and Speech Recognition permissions to the relevant apps or helpers when macOS prompts you. In the Mac-M4 topic, send `/ekran` and open the link in your phone's browser. To speak, tap **Konuşmayı aç** and allow microphone access. [Cursor commands and screen sharing](docs/cursor-telegram-mirror.md)

### Run in the background

Stop the foreground bot with Ctrl+C before starting its service. Run the command for each role you want to enable.

```sh
scripts/mail-service.sh start
scripts/mac-m4-service.sh start
```

Both scripts accept `status` and `stop`. Logs are in `data/logs/`. The optional Mac-M1 and Win11 roles currently support only `/ping`.

### Upgrade an existing installation

Update the checkout in place and run `.venv/bin/python -m pip install -e .`. Existing Telegram topics, Cursor hooks, and macOS permissions carry over. The previous `bildirim` command and `BILDIRIM_*` settings remain supported. If both names are set, the `SEYIR_*` value takes precedence.

## Where your data goes

- The configured model server classifies mail. Its default address is on this Mac. Telegram group members can see alerts and any message preview requested in the topic.
- Cursor hooks relay IDE activity and conversation excerpts to Telegram. Summaries, topic chat, and open-ended screen questions can send relevant text or a screenshot to the configured model provider.
- The desktop panel serves the screen through a Cloudflare tunnel. **Anyone with the active link can control the Mac for that session.** Share it only in a trusted group and use `/ekran dur` to end access.
- Credentials, private network settings, and runtime files under `data/` stay outside Git. Runtime files can contain mail previews, session traces, screen captures, and audio. Remove personal data before sharing diagnostics.

## Test

```sh
python -m unittest discover -s tests -v
```

The test suite uses fixtures. For phone microphone access, real application permissions, and an end-to-end check on your Mac, follow the [first-run checklist](docs/user-checklist.md).

[MIT license](LICENSE)
