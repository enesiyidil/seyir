"""Stream the Cursor window to a Telegram RTMP live broadcast.

ScreenCaptureKit hangs for this helper, so frames come from the system
`screencapture` tool, which already has permission, and ffmpeg pushes them.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from bildirim.config import project_root

_SETUP = (
    "Telegram canlı yayını bağlı değil.\n"
    "1. Grupta Stream with / Başka uygulamayla yayınla ekranını aç.\n"
    "2. Server URL ve Stream key değerlerini .env içine yaz:\n"
    "TELEGRAM_RTMP_URL=\n"
    "TELEGRAM_RTMP_KEY=\n"
    "3. Sonra /ekran\n"
    "Görüntü gidince Telegram’da Start Streaming’e bas."
)

_LIST_SWIFT = r'''
import CoreGraphics
let mode = CGDisplayCopyDisplayMode(CGMainDisplayID())
let screenW = mode?.pixelWidth ?? CGDisplayPixelsWide(CGMainDisplayID())
let screenH = mode?.pixelHeight ?? CGDisplayPixelsHigh(CGMainDisplayID())
print("SCREEN\t\(screenW)\t\(screenH)")
let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] ?? []
for w in info {
  let owner = w[kCGWindowOwnerName as String] as? String ?? ""
  if owner != "Cursor" { continue }
  let name = w[kCGWindowName as String] as? String ?? ""
  let num = w[kCGWindowNumber as String] as? Int ?? 0
  let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
  let x = b["X"] as? Double ?? 0
  let y = b["Y"] as? Double ?? 0
  let width = b["Width"] as? Double ?? 0
  let height = b["Height"] as? Double ?? 0
  print("WIN\t\(num)\t\(Int(x))\t\(Int(y))\t\(Int(width))\t\(Int(height))\t\(name)")
}
'''


@dataclass(frozen=True)
class StreamResult:
    ok: bool
    text: str


def state_path() -> Path:
    return project_root() / "data" / "ekran.json"


def status_path() -> Path:
    return project_root() / "data" / "ekran.status"


def rtmp_destination() -> str | None:
    url = (os.environ.get("TELEGRAM_RTMP_URL") or "").strip()
    key = (os.environ.get("TELEGRAM_RTMP_KEY") or "").strip()
    if not url or not key:
        return None
    if key in url:
        return url
    return url.rstrip("/") + "/" + key


def ffmpeg_bin() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    brew = Path("/opt/homebrew/bin/ffmpeg")
    return str(brew) if brew.is_file() else None


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_state() -> dict[str, int]:
    path = state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, int] = {}
    if isinstance(data, dict):
        for key in ("push_pid", "ffmpeg_pid", "voice_pid", "talk_pid", "tunnel_pid", "overlay_pid"):
            try:
                out[key] = int(data.get(key) or 0)
            except (TypeError, ValueError):
                out[key] = 0
    return out


def is_running() -> bool:
    state = _read_state()
    return any(
        _alive(state.get(key, 0))
        for key in ("push_pid", "ffmpeg_pid", "talk_pid")
    )


_STOP = threading.Lock()
_DESKTOP_IDLE = 15
_DESKTOP_WAIT = 180
_SHARE_MAX = 15 * 60
_WINDOW_JOIN = 25


def _marker(name: str) -> Path:
    return project_root() / "data" / name


def _clear_markers() -> None:
    for name in ("ekran-beat", "ekran-live", "ekran-ended"):
        path = _marker(name)
        if path.exists():
            path.unlink()


def stop_stream() -> StreamResult:
    with _STOP:
        state = _read_state()
        stopped = False
        for key in ("overlay_pid", "ffmpeg_pid", "push_pid", "voice_pid", "tunnel_pid", "talk_pid"):
            pid = state.get(key, 0)
            if pid and _alive(pid):
                os.kill(pid, signal.SIGTERM)
                stopped = True
        time.sleep(0.3)
        for key in ("overlay_pid", "ffmpeg_pid", "push_pid", "voice_pid", "tunnel_pid", "talk_pid"):
            pid = state.get(key, 0)
            if pid and _alive(pid):
                os.kill(pid, signal.SIGKILL)
        subprocess.run(["pkill", "-f", "[s]creen-helper corners"], capture_output=True, check=False)
        for path in (state_path(), status_path()):
            if path.exists():
                path.unlink()
        _clear_markers()
        if stopped:
            return StreamResult(ok=True, text="Ekran yayını durdu.")
        return StreamResult(ok=True, text="Açık ekran yayını yoktu.")


def _full_state() -> dict[str, object]:
    path = state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _watch_once() -> None:
    data = _full_state()
    if not data:
        return
    mode = str(data.get("mode") or "")
    try:
        started = float(data.get("started") or 0)
    except (TypeError, ValueError):
        started = 0
    now = time.time()
    running = is_running()
    overlay = int(data.get("overlay_pid") or 0) if str(data.get("overlay_pid") or "").isdigit() or isinstance(data.get("overlay_pid"), int) else 0
    if overlay and _alive(overlay) and not running:
        stop_stream()
        return
    if not running:
        return
    if started and now - started > _SHARE_MAX:
        stop_stream()
        return
    if mode == "desktop":
        beat = _marker("ekran-beat")
        if beat.is_file():
            raw = beat.read_text(encoding="utf-8").strip()
            if raw == "0":
                stop_stream()
                return
            try:
                seen = float(raw)
            except ValueError:
                seen = 0
            if seen and now - seen > _DESKTOP_IDLE:
                stop_stream()
        elif not started or now - started > _DESKTOP_WAIT:
            stop_stream()
        return
    if mode == "window":
        if _marker("ekran-ended").is_file():
            stop_stream()
            return
        age = now - started if started else _WINDOW_JOIN + 1
        if not _marker("ekran-live").is_file() and age > _WINDOW_JOIN:
            stop_stream()


def arm_watch() -> None:
    if getattr(arm_watch, "on", False):
        return
    setattr(arm_watch, "on", True)

    def loop() -> None:
        while True:
            time.sleep(2)
            try:
                _watch_once()
            except Exception:
                continue

    threading.Thread(target=loop, name="ekran-watch", daemon=True).start()


def _cursor_crop(project: str) -> tuple[str, str] | None:
    """Return an ffmpeg crop filter for the Cursor window, in screen pixels."""
    proc = subprocess.run(
        ["swift", "-e", _LIST_SWIFT],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    screen_w = screen_h = 0
    best: tuple[int, int, int, int, int, str] | None = None
    best_area = -1
    named: tuple[int, int, int, int, int, str] | None = None
    named_area = -1
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if parts[0] == "SCREEN" and len(parts) >= 3:
            screen_w, screen_h = int(parts[1]), int(parts[2])
            continue
        if parts[0] != "WIN" or len(parts) < 7:
            continue
        wid, x, y, w, h = (
            int(parts[1]),
            int(parts[2]),
            int(parts[3]),
            int(parts[4]),
            int(parts[5]),
        )
        name = parts[6]
        area = w * h
        if area > best_area:
            best_area = area
            best = (wid, x, y, w, h, name)
        if project and project.lower() in name.lower() and area > named_area:
            named_area = area
            named = (wid, x, y, w, h, name)
    chosen = named or best
    if not chosen or screen_w <= 0 or chosen[3] <= 0:
        return None
    wid, x, y, w, h, name = chosen
    scale = max(1, int(round(screen_w / max(w, 1))))
    cx, cy = int(x * scale), int(y * scale)
    cw, ch = int(w * scale), int(h * scale)
    if cx < 0:
        cw += cx
        cx = 0
    if cy < 0:
        ch += cy
        cy = 0
    cw = min(cw, screen_w - cx)
    ch = min(ch, screen_h - cy)
    cw -= cw % 2
    ch -= ch % 2
    if cw < 2 or ch < 2:
        return None
    return f"crop={cw}:{ch}:{cx}:{cy}", (name or "Cursor"), (cx, cy, cw, ch), wid


def _screen_device(ffmpeg: str) -> str:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    for line in (proc.stderr or "").splitlines():
        if "Capture screen" in line and "[" in line:
            start = line.find("[")
            end = line.find("]", start)
            if start != -1 and end != -1 and line[start + 1 : end].isdigit():
                return line[start + 1 : end]
    return "2"


def say_path() -> Path:
    return project_root() / "data" / "ekran-say.txt"


def request_speech(text: str) -> None:
    path = say_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _speech_pcm(text: str) -> bytes:
    folder = project_root() / "data"
    folder.mkdir(parents=True, exist_ok=True)
    aiff = folder / "ekran-say.aiff"
    raw = folder / "ekran-say.pcm"
    subprocess.run(
        ["say", "-v", "Yelda", "-o", str(aiff), text],
        capture_output=True,
        check=False,
    )
    ffmpeg = ffmpeg_bin()
    if not ffmpeg or not aiff.is_file():
        return b""
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(aiff),
            "-f",
            "s16le",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(raw),
        ],
        capture_output=True,
        check=False,
    )
    if not raw.is_file():
        return b""
    return raw.read_bytes()


def _feed_audio(stream: subprocess.Popen[bytes]) -> None:
    stdin = stream.stdin
    if stdin is None:
        return
    frame = 2048 * 2 * 2
    silence = b"\x00" * frame
    pending = b""
    try:
        while stream.poll() is None:
            cue = say_path()
            if cue.is_file() and not pending:
                text = cue.read_text(encoding="utf-8").strip()
                cue.unlink(missing_ok=True)
                if text:
                    pending = _speech_pcm(text)
            if pending:
                chunk = pending[:frame]
                pending = pending[frame:]
                if len(chunk) < frame:
                    chunk += b"\x00" * (frame - len(chunk))
                stdin.write(chunk)
            else:
                stdin.write(silence)
            stdin.flush()
            time.sleep(2048 / 44100)
    except (BrokenPipeError, OSError):
        return


def push_forever(mode: str = "window", project: str = "") -> None:
    dest = rtmp_destination()
    ffmpeg = ffmpeg_bin()
    status = status_path()
    status.parent.mkdir(parents=True, exist_ok=True)
    if not ffmpeg or not dest:
        status.write_text("missing ffmpeg or rtmp\n", encoding="utf-8")
        return
    if mode == "desktop":
        crop_filter, label = "null", "Mac"
        wid = None
    else:
        crop = _cursor_crop(project)
        if not crop:
            status.write_text("NO_WINDOW\n", encoding="utf-8")
            return
        crop_filter, label, _rect, wid = crop
    device = _screen_device(ffmpeg)
    log_path = project_root() / "data" / "logs" / "ekran.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("ab")
    ff = subprocess.Popen(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "avfoundation",
            "-framerate",
            "8",
            "-pixel_format",
            "nv12",
            "-capture_cursor",
            "1",
            "-i",
            f"{device}:none",
            "-f",
            "s16le",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-i",
            "pipe:0",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-r",
            "8",
            "-fps_mode",
            "cfr",
            "-vf",
            ("scale=1280:720,setsar=1,fps=8,format=yuv420p" if mode == "desktop" else crop_filter + ",scale=1280:720,setsar=1,fps=8,format=yuv420p"),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-profile:v",
            "main",
            "-level",
            "4.0",
            "-pix_fmt",
            "yuv420p",
            "-bf",
            "0",
            "-g",
            "16",
            "-b:v",
            "1800k",
            "-maxrate",
            "1800k",
            "-bufsize",
            "3600k",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-f",
            "flv",
            dest,
        ],
        stdin=subprocess.PIPE,
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    threading.Thread(target=_feed_audio, args=(ff,), name="ekran-audio", daemon=True).start()
    request_speech("Bu pencere yayında.")
    state_path().write_text(
        json.dumps(
            {
                "push_pid": os.getpid(),
                "ffmpeg_pid": ff.pid,
                "label": label,
                "mode": mode,
                "window_id": wid,
            }
        ) + "\n",
        encoding="utf-8",
    )
    time.sleep(2)
    if ff.poll() is not None:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-400:]
        status.write_text(f"failed\n{tail}\n", encoding="utf-8")
        return
    status.write_text("ok\n", encoding="utf-8")
    ff.wait()


def mark_window_live() -> None:
    if str(_full_state().get("mode") or "") != "window":
        return
    _marker("ekran-live").write_text(str(time.time()), encoding="utf-8")


def mark_window_ended() -> None:
    if str(_full_state().get("mode") or "") != "window":
        return
    _marker("ekran-ended").write_text(str(time.time()), encoding="utf-8")
    stop_stream()


def start_stream(
    *,
    project: str = "",
    mode: str = "window",
    topic_id: int | None = None,
    conversation_id: str = "",
    short_id: str = "",
) -> StreamResult:
    if is_running():
        stop_stream()
    _clear_markers()
    from bildirim.voice_control import write_session

    write_session(
        {
            "mode": mode,
            "project": project,
            "topic_id": topic_id,
            "conversation_id": conversation_id,
            "short_id": short_id,
        }
    )
    if mode == "desktop":
        return _start_desktop()
    return _start_window(project, short_id)


def _start_desktop() -> StreamResult:
    from bildirim.talk_bridge import open_tunnel, prove_public

    token = secrets.token_urlsafe(32)
    talk = subprocess.Popen(
        [sys.executable, "-m", "bildirim.talk_bridge", "serve"],
        env={**os.environ, "BILDIRIM_SCREEN_TOKEN": token},
        cwd=str(project_root()),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    tunnel, public = open_tunnel(f"/ready?t={token}")
    if not public or tunnel is None:
        if tunnel is not None:
            tunnel.kill()
        talk.kill()
        return StreamResult(
            ok=False,
            text="Bağlantı telefonda açılacak kadar hazır değil. Link gönderilmedi.",
        )
    page = f"{public.rstrip('/')}/?t={token}"
    ok, evidence = prove_public(f"{public.rstrip('/')}/ready?t={token}")
    if not ok:
        tunnel.kill()
        talk.kill()
        return StreamResult(
            ok=False,
            text=f"Bağlantı doğrulanamadı ({evidence}). Link gönderilmedi.",
        )
    talk_url = page
    from bildirim.screen_presence import start_corners

    overlay = start_corners()
    state_path().parent.mkdir(parents=True, exist_ok=True)
    state_path().write_text(
        json.dumps(
            {
                "talk_pid": talk.pid,
                "tunnel_pid": tunnel.pid if tunnel is not None else 0,
                "overlay_pid": overlay,
                "mode": "desktop",
                "started": time.time(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return StreamResult(
        ok=True,
        text=(
            "Mac ekranı ve sohbet hazır.\n"
            f"{talk_url}\n"
            "Sayfayı kapatınca yayın durur. Açık kalırsa 15 dakikada durur.\n"
            "Durdurmak: /ekran dur"
        ),
    )


def _start_window(project: str, short_id: str) -> StreamResult:
    from bildirim.ide_send import focus_chat

    focus_chat(project)
    if not ffmpeg_bin():
        return StreamResult(ok=False, text="ffmpeg yok.")
    if not rtmp_destination():
        return StreamResult(ok=False, text=_SETUP)
    status_path().parent.mkdir(parents=True, exist_ok=True)
    if status_path().exists():
        status_path().unlink()
    subprocess.Popen(
        [sys.executable, "-m", "bildirim.ide_stream", "push", "window", project or ""],
        cwd=str(project_root()),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 12
    heard = ""
    while time.time() < deadline:
        if status_path().is_file():
            heard = status_path().read_text(encoding="utf-8", errors="replace").strip()
            if heard.startswith(("ok", "NO_WINDOW", "failed", "missing")):
                break
        time.sleep(0.3)
    if heard.startswith("NO_WINDOW"):
        stop_stream()
        return StreamResult(ok=False, text="Cursor penceresi bulunamadı.")
    if heard.startswith("failed") or heard.startswith("missing"):
        stop_stream()
        return StreamResult(ok=False, text=f"Yayın başlamadı.\n{heard[:300]}")
    from bildirim.screen_presence import start_corners

    data = _full_state()
    data["overlay_pid"] = start_corners()
    data["mode"] = "window"
    data["started"] = time.time()
    state_path().write_text(json.dumps(data) + "\n", encoding="utf-8")
    where = short_id or project or "Cursor"
    return StreamResult(
        ok=True,
        text=(
            f"Bu pencere yayında: {where}.\n"
            "Telegram’da Start Streaming’e bas.\n"
            "Canlı yayın kapanınca veya kimse açmazsa yayın durur.\n"
            "Durdurmak: /ekran dur"
        ),
    )


def _cli() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "push":
        mode = sys.argv[2] if len(sys.argv) > 2 else "window"
        project = sys.argv[3] if len(sys.argv) > 3 else ""
        from bildirim.config import load_settings

        load_settings()
        push_forever(mode, project)


if __name__ == "__main__":
    _cli()
