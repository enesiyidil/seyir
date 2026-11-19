# How Seyir classifies mail

The watcher reads unread messages from `MAIL_INBOX` under `MAIL_ACCOUNT` in Apple Mail. Local rules recognize common automated notifications and meeting responses. For remaining messages, the watcher sends the sender, subject, date, and first 3,000 characters of the body to the configured Qwen server. `MAIL_INTERNAL_DOMAINS` helps identify external senders.

| Classification | Telegram alert | Apple Mail |
| --- | --- | --- |
| Meeting | Subject, time, and participants | Stays unread |
| Important | Sender and subject | Stays unread |
| Noise | None | Marked as read |
| Uncertain | None | Stays unread |

Seyir stores processing history in `data/processed_mail.json`. Reply to an important alert with `içerik` (“content”) to request its saved body preview. Sending the word on its own in the Mail topic retrieves the latest alert. `seyir mail-once` processes the inbox once and exits.
