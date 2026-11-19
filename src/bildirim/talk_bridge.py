"""Phone live-talk page: the mic comes to the Mac, the reply is spoken back."""

from __future__ import annotations

import base64
from collections import deque
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import which
from urllib.parse import parse_qs, urlparse

from bildirim.config import project_root
from bildirim.voice_input import TeamsDraft

PORT = 8766


_PANEL = Path(__file__).with_name("panel")
_SHOT = threading.Lock()
_INPUT = threading.Lock()
_CONVERSATION = threading.Lock()
_TEAMS_DRAFT = TeamsDraft()
_HISTORY: deque[tuple[str, str]] = deque(maxlen=4)


def grab_screen() -> bytes:
    with _SHOT, tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "frame.jpg"
        for command in (
            ["/usr/sbin/screencapture", "-x", "-m", "-t", "jpg", str(path)],
            ["sips", "-Z", "1440", "-s", "formatOptions", "60", str(path)],
        ):
            proc = subprocess.run(command, capture_output=True, timeout=8, check=False)
            if proc.returncode:
                return b""
        return path.read_bytes()


def note_seen() -> None:
    path = project_root() / "data" / "ekran-beat"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def note_closed() -> None:
    path = project_root() / "data" / "ekran-beat"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("0", encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _token_ok(self) -> bool:
        given = parse_qs(urlparse(self.path).query).get("t", [""])[0]
        expected = os.environ.get("BILDIRIM_SCREEN_TOKEN", "")
        return bool(expected and given.isascii()) and secrets.compare_digest(given, expected)

    def _send(self, status: int, mime: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, **payload: object) -> None:
        self._send(status, "application/json; charset=utf-8", json.dumps(payload).encode())

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/desk.js", "/speech-gate.js"}:
            self._send(200, "text/javascript", (_PANEL / path[1:]).read_bytes())
            return
        if not self._token_ok():
            self._json(403, error="Ekran bağlantısı geçersiz. Telegram’dan yeni bağlantı aç.")
        elif path == "/ready":
            self._json(200, ok=True)
        elif path == "/":
            self._send(200, "text/html; charset=utf-8", (_PANEL / "desk.html").read_bytes())
        elif path == "/frame.jpg":
            note_seen()
            try:
                frame = grab_screen()
            except (OSError, subprocess.SubprocessError):
                frame = b""
            if frame:
                self._send(200, "image/jpeg", frame)
            else:
                self._json(503, error="Mac ekranı alınamadı. Ekran Kaydı iznini kontrol et.")
        else:
            self._json(404, error="Sayfa bulunamadı.")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not self._token_ok():
            self._json(403, error="Oturum sona erdi. Telegram’dan yeni bağlantı aç.")
            return
        if path == "/bye":
            note_closed()
            self._json(200, ok=True)
            return
        if path not in {"/control", "/talk", "/chat"}:
            self._json(404, error="İşlem bulunamadı.")
            return
        try:
            limit = 8_000_000 if path == "/talk" else 32_000
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= limit:
                self._json(413, error="İstek boş veya çok büyük.")
                return
            note_seen()
            body = self.rfile.read(length)
            if path == "/talk":
                payload = {}
            else:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError("İstek biçimi geçersiz.")
            if path == "/control":
                from bildirim.desktop_control import manual_control

                with _INPUT:
                    manual_control(payload)
                self._json(200, ok=True)
                return
            if not _CONVERSATION.acquire(blocking=False):
                self._json(409, error="Asistan önceki yanıtı hazırlıyor.")
                return
            try:
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    if path == "/talk":
                        from bildirim.voice_control import transcribe_file

                        src = root / "question.bin"
                        src.write_bytes(body)
                        text, error = transcribe_file(src)
                        if not text:
                            self._json(422, error=error or "Ses anlaşılamadı.")
                            return
                    else:
                        text = payload.get("text")
                        if not isinstance(text, str) or not text.strip():
                            raise ValueError("Mesaj boş.")
                    from bildirim.voice_control import handle_spoken

                    history = "\n".join(f"Kullanıcı: {q}\nAsistan: {a}" for q, a in _HISTORY)
                    with _INPUT:
                        reply = handle_spoken(text, history=history, dialog=_TEAMS_DRAFT)
                    _HISTORY.append((text[:600], reply[:600]))
                    wav = _say_wav(reply, root)
                    self._json(200, heard=text, reply=reply, wav=base64.b64encode(wav).decode())
            finally:
                _CONVERSATION.release()
        except (ValueError, UnicodeError):
            self._json(400, error="Geçersiz metin, tuş veya ekran konumu.")
        except PermissionError as exc:
            self._json(403, error=str(exc))
        except (OSError, subprocess.SubprocessError, RuntimeError):
            self._json(503, error="Mac işlemi tamamlayamadı. Bağlantıyı ve izinleri kontrol et.")


def _say_wav(text: str, folder: Path) -> bytes:
    wav = folder / "reply.wav"
    try:
        subprocess.run(["say", "-v", "Yelda", "--file-format=WAVE", "--data-format=LEI16@16000",
                        "-o", str(wav)], input=text[:1200].encode(), capture_output=True,
                       check=True, timeout=20)
        return wav.read_bytes()
    except (OSError, subprocess.SubprocessError):
        return b""


def serve() -> None:
    from bildirim.config import load_settings

    load_settings()
    if not os.environ.get("BILDIRIM_SCREEN_TOKEN"):
        raise SystemExit("Ekran bağlantısını Mac-M4 konusundan aç.")
    with ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as server:
        server.serve_forever()


def cloudflared_bin() -> str:
    for candidate in ("/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared"):
        if Path(candidate).is_file():
            return candidate
    return which("cloudflared") or ""


def _lookup_a(host: str, server: str) -> str:
    try:
        out = subprocess.check_output(
            ["dig", "+time=2", "+tries=1", f"@{server}", host, "A", "+short"],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in out.splitlines():
        line = line.strip()
        if line and line[0].isdigit() and ":" not in line:
            return line
    return ""


def _curl_status(host: str, ip: str, url: str) -> str:
    proc = subprocess.run(
        [
            "curl",
            "-4",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "12",
            "--resolve",
            f"{host}:443:{ip}",
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or "").strip()


def prove_public(url: str) -> tuple[bool, str]:
    last = "doğrulama yok"
    for _ in range(4):
        host = urlparse(url).hostname or ""
        ip_a = _lookup_a(host, "1.1.1.1")
        ip_b = _lookup_a(host, "8.8.8.8")
        if not ip_a or not ip_b:
            last = f"dns 1.1.1.1={ip_a or 'yok'} 8.8.8.8={ip_b or 'yok'}"
            time.sleep(1)
            continue
        code_a = _curl_status(host, ip_a, url)
        code_b = _curl_status(host, ip_b, url)
        last = f"1.1.1.1={ip_a} http {code_a or 'yok'}; 8.8.8.8={ip_b} http {code_b or 'yok'}"
        if code_a == "200" and code_b == "200":
            return True, last
        time.sleep(1)
    return False, last


def open_tunnel(page_path: str = "/") -> tuple[subprocess.Popen[str] | None, str]:
    binary = cloudflared_bin()
    if not binary:
        return None, ""
    log_path = project_root() / "data" / "logs" / "cloudflared.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_start = log_path.stat().st_size if log_path.exists() else 0
    log_fh = log_path.open("ab")
    proc = subprocess.Popen(
        [
            binary,
            "tunnel",
            "--url",
            f"http://127.0.0.1:{PORT}",
            "--no-autoupdate",
            "--metrics",
            "127.0.0.1:20245",
            "--logfile",
            str(log_path),
        ],
        stdout=log_fh,
        stderr=log_fh,
    )
    log_fh.close()
    hostname = ""
    for _ in range(60):
        time.sleep(0.5)
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen("http://127.0.0.1:20245/quicktunnel", timeout=1) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            hostname = str(payload.get("hostname") or "")
        except (OSError, json.JSONDecodeError, urllib.error.URLError):
            hostname = ""
        if not hostname and log_path.is_file():
            with log_path.open("rb") as log:
                log.seek(log_start)
                text = log.read().decode("utf-8", errors="replace")
            for part in text.replace("|", " ").split():
                if part.startswith("https://") and "trycloudflare.com" in part:
                    hostname = part.removeprefix("https://").strip().rstrip(").,/")
                    break
        if not hostname:
            continue
        public = f"https://{hostname}"
        ip_a = _lookup_a(hostname, "1.1.1.1")
        ip_b = _lookup_a(hostname, "8.8.8.8")
        if not ip_a or not ip_b:
            continue
        code = _curl_status(hostname, ip_a, public + page_path)
        if code == "200":
            return proc, public
    if proc.poll() is None:
        proc.kill()
    return None, ""


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve()
