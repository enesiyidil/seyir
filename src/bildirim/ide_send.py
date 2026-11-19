"""Type into the open Cursor IDE agent and submit.

Cursor's composer is not in the accessibility tree, so this raises the
matching window, focuses Agent, pastes, presses Return, then restores
the previously frontmost app.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

_RAISE_SCRIPT = r'''
on run argv
  set projectName to item 1 of argv
  tell application "System Events"
    if not (exists process "Cursor") then error "Cursor açık değil."
    set prevApp to name of first application process whose frontmost is true
    tell process "Cursor"
      if (count of windows) is 0 then error "Cursor penceresi yok."
      set best to 1
      set bestArea to -1
      set matched to 0
      set i to 0
      repeat with w in windows
        set i to i + 1
        set nm to ""
        set doc to ""
        try
          set nm to name of w as text
        end try
        try
          set doc to (value of attribute "AXDocument" of w) as text
        end try
        if projectName is not "" and (nm contains projectName or doc contains projectName) then
          set matched to i
        end if
        try
          set sz to size of w
          set area to (item 1 of sz) * (item 2 of sz)
          if area > bestArea then
            set bestArea to area
            set best to i
          end if
        end try
      end repeat
      if matched is not 0 then
        set best to matched
      end if
      perform action "AXRaise" of window best
      set frontmost to true
      set picked to ""
      try
        set picked to name of window best as text
      end try
      return prevApp & linefeed & picked
    end tell
  end tell
end run
'''

_TYPE_SCRIPT = r'''
tell application "System Events"
  tell process "Cursor" to set frontmost to true
end tell
delay 0.2
tell application "System Events"
  keystroke "p" using {command down, shift down}
  delay 0.35
  keystroke "Focus Agent"
  delay 0.35
  key code 36
  delay 0.4
  keystroke "v" using {command down}
  delay 0.15
  key code 36
end tell
return "sent"
'''

_RESTORE_SCRIPT = r'''
on run argv
  set prevApp to item 1 of argv
  tell application "System Events"
    if exists process prevApp then
      set frontmost of process prevApp to true
    end if
  end tell
end run
'''


@dataclass(frozen=True)
class SendResult:
    ok: bool
    text: str


def cursor_window_titles() -> list[str]:
    script = '''
tell application "System Events"
  if not (exists process "Cursor") then return ""
  tell process "Cursor"
    set names to {}
    repeat with w in windows
      set end of names to (name of w as text)
    end repeat
    set AppleScript's text item delimiters to linefeed
    return names as text
  end tell
end tell
'''
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


def _run_osascript(script: str, *args: str, timeout: float = 6) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/osascript", "-e", script, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _permission_text(detail: str) -> str | None:
    low = detail.lower()
    if "not allowed" in low or "1002" in low or "-1719" in low or "assistive" in low:
        return (
            "Erişilebilirlik izni gerekli. Sistem Ayarları → Gizlilik ve Güvenlik "
            "→ Erişilebilirlik içinde Python’u aç. İzin penceresi arkada kalmış olabilir. "
            "İzin verince uygulama yeniden başlayabilir; sonra /yaz tekrar."
        )
    return None


def focus_chat(project: str = "") -> SendResult:
    """Bring the Cursor window forward and focus the Agent input. Does not type."""
    try:
        raised = _run_osascript(_RAISE_SCRIPT, project or "", timeout=6)
    except subprocess.TimeoutExpired:
        return SendResult(ok=False, text="Cursor penceresi seçilemedi.")
    if raised.returncode != 0:
        detail = (raised.stderr or raised.stdout or "osascript").strip().splitlines()
        last = detail[-1] if detail else "osascript"
        return SendResult(ok=False, text=f"Sohbet seçilemedi: {last[:200]}")
    focus_script = r'''
tell application "System Events"
  tell process "Cursor" to set frontmost to true
end tell
delay 0.2
tell application "System Events"
  keystroke "p" using {command down, shift down}
  delay 0.3
  keystroke "Focus Agent"
  delay 0.25
  key code 36
end tell
return "ok"
'''
    try:
        focused = _run_osascript(focus_script, timeout=6)
    except subprocess.TimeoutExpired:
        return SendResult(ok=False, text="Agent kutusu odaklanamadı.")
    if focused.returncode != 0:
        return SendResult(ok=False, text="Agent kutusu odaklanamadı.")
    lines = [ln.strip() for ln in (raised.stdout or "").splitlines() if ln.strip()]
    picked = lines[1] if len(lines) > 1 else (project or "Cursor")
    return SendResult(ok=True, text=f"Sohbet seçili: {picked}")


def send_to_ide(text: str, *, project: str = "") -> SendResult:
    body = (text or "").strip()
    if not body:
        return SendResult(ok=False, text="Yazılacak metin yok.")
    if len(body) > 4000:
        body = body[:4000]

    previous = subprocess.run(["pbpaste"], capture_output=True, check=False).stdout
    try:
        copied = subprocess.run(["pbcopy"], input=body.encode("utf-8"), check=False)
        if copied.returncode != 0:
            return SendResult(ok=False, text="Pano yazılamadı.")
        try:
            raised = _run_osascript(_RAISE_SCRIPT, project or "", timeout=6)
        except subprocess.TimeoutExpired:
            return SendResult(ok=False, text="Cursor penceresi öne alınamadı (zaman aşımı).")
        if raised.returncode != 0:
            detail = (raised.stderr or raised.stdout or "osascript").strip().splitlines()
            last = detail[-1] if detail else "osascript"
            return SendResult(ok=False, text=_permission_text(last) or f"Pencere seçilemedi: {last[:240]}")
        lines = [ln.strip() for ln in (raised.stdout or "").splitlines() if ln.strip()]
        prev_app = lines[0] if lines else ""
        picked = lines[1] if len(lines) > 1 else "en büyük Cursor penceresi"
        try:
            typed = _run_osascript(_TYPE_SCRIPT, timeout=8)
        except subprocess.TimeoutExpired:
            return SendResult(
                ok=False,
                text=(
                    "Metin yapıştırılamadı (tuş zaman aşımı). "
                    "Erişilebilirlik iznini Python için kontrol et, sonra /yaz tekrar."
                ),
            )
        if typed.returncode != 0:
            detail = (typed.stderr or typed.stdout or "osascript").strip().splitlines()
            last = detail[-1] if detail else "osascript"
            return SendResult(ok=False, text=_permission_text(last) or f"IDE'ye yazılamadı: {last[:240]}")
        if prev_app and prev_app != "Cursor":
            try:
                _run_osascript(_RESTORE_SCRIPT, prev_app, timeout=3)
            except subprocess.TimeoutExpired:
                pass
        where = picked or project or "Cursor"
        return SendResult(ok=True, text=f"IDE agent kutusuna yazıldı ({where}).")
    finally:
        subprocess.run(["pbcopy"], input=previous, check=False)
