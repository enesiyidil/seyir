"""Corner marks while the screen is shared, and a fast read of the words on it."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from bildirim.config import project_root

_BIN = project_root() / "scripts" / "bin" / "screen-helper"
_SRC = project_root() / "scripts" / "screen_helper.swift"


def helper_bin() -> Path | None:
    if _BIN.is_file() and _BIN.stat().st_mtime >= _SRC.stat().st_mtime:
        return _BIN
    _BIN.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "swiftc", "-O", "-o", str(_BIN), str(_SRC),
            "-framework", "AppKit", "-framework", "Vision",
            "-framework", "ImageIO", "-framework", "Foundation",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0 or not _BIN.is_file():
        return None
    return _BIN


def start_corners() -> int:
    binary = helper_bin()
    if binary is None:
        return 0
    proc = subprocess.Popen(
        [str(binary), "corners"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid


def stop_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def read_screen(image: Path) -> str:
    binary = helper_bin()
    if binary is None or not image.is_file():
        return "Ekran yazıları okunamadı."
    proc = subprocess.run(
        [str(binary), "ocr", str(image)],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    text = (proc.stdout or "").strip()
    if not text:
        return "Ekranda okunabilir yazı yok."
    return "Yazı ve tıklama noktası (x y metin):\n" + text
