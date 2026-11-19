"""Read and update Exchange mail through Apple Mail."""

from __future__ import annotations

import os
import subprocess

from bildirim.mail.rules import MailItem

MSG_START = "===MSG==="
BODY_START = "===BODY==="
MSG_END = "===END==="


def _run_file(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "osascript failed").strip()
        raise RuntimeError(err)
    return result.stdout


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _mailbox() -> str:
    account = _escape(os.environ.get("MAIL_ACCOUNT", "Exchange"))
    inbox = _escape(os.environ.get("MAIL_INBOX", "Gelen Kutusu"))
    return f'mailbox "{inbox}" of account "{account}"'


def list_unread(limit: int = 20) -> list[MailItem]:
    script = f'''
tell application "Mail"
  set inboxBox to {_mailbox()}
  set unreadMsgs to (messages of inboxBox whose read status is false)
  set totalCount to count of unreadMsgs
  set limitCount to {int(limit)}
  if totalCount < limitCount then set limitCount to totalCount
  set outText to ""
  set idx to 0
  repeat with msgRef in unreadMsgs
    set idx to idx + 1
    if idx > limitCount then exit repeat
    set mid to id of msgRef as string
    set subjText to subject of msgRef
    set fromText to sender of msgRef
    set dateText to date received of msgRef as string
    set bodyText to content of msgRef
    if (count of bodyText) > 3500 then set bodyText to text 1 thru 3500 of bodyText
    set outText to outText & "{MSG_START}" & linefeed
    set outText to outText & "id=" & mid & linefeed
    set outText to outText & "subject=" & subjText & linefeed
    set outText to outText & "sender=" & fromText & linefeed
    set outText to outText & "date=" & dateText & linefeed
    set outText to outText & "{BODY_START}" & linefeed
    set outText to outText & bodyText & linefeed
    set outText to outText & "{MSG_END}" & linefeed
  end repeat
  return outText
end tell
'''
    raw = _run_file(script)
    return _parse_messages(raw)


def _parse_messages(raw: str) -> list[MailItem]:
    items: list[MailItem] = []
    chunks = raw.split(MSG_START)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if MSG_END in chunk:
            chunk = chunk.split(MSG_END, 1)[0]
        if BODY_START not in chunk:
            continue
        header, body = chunk.split(BODY_START, 1)
        fields: dict[str, str] = {}
        for line in header.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
        message_id = fields.get("id", "").strip()
        if not message_id:
            continue
        items.append(
            MailItem(
                message_id=message_id,
                subject=fields.get("subject", ""),
                sender=fields.get("sender", ""),
                date_received=fields.get("date", ""),
                body=body.strip(),
                unread=True,
            )
        )
    return items


def mark_read(message_id: str) -> None:
    mid = _escape(message_id)
    script = f'''
tell application "Mail"
  set inboxBox to {_mailbox()}
  set targetId to "{mid}"
  repeat with msgRef in messages of inboxBox
    if (id of msgRef as string) is equal to targetId then
      set read status of msgRef to true
      return "ok"
    end if
  end repeat
  return "missing"
end tell
'''
    status = _run_file(script).strip()
    if status != "ok":
        raise RuntimeError(f"Mail id {message_id} işaretlenemedi: {status}")


def get_body(message_id: str, max_chars: int = 6000) -> str:
    mid = _escape(message_id)
    script = f'''
tell application "Mail"
  set inboxBox to {_mailbox()}
  set targetId to "{mid}"
  repeat with msgRef in messages of inboxBox
    if (id of msgRef as string) is equal to targetId then
      set bodyText to content of msgRef
      if (count of bodyText) > {int(max_chars)} then set bodyText to text 1 thru {int(max_chars)} of bodyText
      return bodyText
    end if
  end repeat
  return ""
end tell
'''
    return _run_file(script)
