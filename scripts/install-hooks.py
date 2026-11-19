"""Register the mirror alongside existing user hooks without replacing other tools."""

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import tempfile

ROOT = Path(__file__).resolve().parent.parent
EVENTS = (
    "sessionStart", "sessionEnd", "beforeSubmitPrompt", "afterAgentResponse",
    "stop", "preToolUse", "postToolUse", "beforeShellExecution",
    "beforeMCPExecution", "subagentStart", "beforeReadFile",
)


def install(directory: Path, replace_legacy: bool) -> None:
    python = ROOT / ".venv/bin/python"
    if not python.is_file():
        raise SystemExit("Önce README'deki .venv kurulumunu tamamlayın.")
    path = directory / "hooks.json"
    config = json.loads(path.read_text()) if path.exists() else {"version": 1}
    if config.get("version", 1) != 1:
        raise SystemExit("Cursor hooks.json sürümü desteklenmiyor.")
    hooks = config.setdefault("hooks", {})
    command = shlex.join([str(python), str(ROOT / "scripts/bildirim-mirror.py")])
    legacy = str(directory / "hooks/bildirim-mirror.py")
    for event in EVENTS:
        entries = hooks.setdefault(event, [])
        if replace_legacy:
            entries[:] = [item for item in entries if item.get("command") != legacy]
        if not any(item.get("command") == command for item in entries):
            entries.append({"command": command})

    secret = ROOT / "data/bridge.secret"
    secret.parent.mkdir(mode=0o700, exist_ok=True)
    try:
        fd = os.open(secret, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as file:
            file.write(secrets.token_urlsafe(32))
    directory.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    if not path.exists() or path.read_text() != rendered:
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as tmp:
            tmp.write(rendered)
        os.replace(tmp.name, path)
    print(f"Cursor hook ayarları hazır: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cursor-dir", type=Path, default=Path.home() / ".cursor")
    parser.add_argument("--replace-legacy", action="store_true",
                        help="Eski ~/.cursor/hooks/bildirim-mirror.py kaydını taşı")
    args = parser.parse_args()
    install(args.cursor_dir, args.replace_legacy)
