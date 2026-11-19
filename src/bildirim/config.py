"""Load Seyir settings from the environment and the project .env file."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROLE_TOKEN_ENV: dict[str, str] = {
    "mail": "TELEGRAM_BOT_TOKEN_MAIL",
    "mac-m4": "TELEGRAM_BOT_TOKEN_MAC_M4",
    "mac-m1": "TELEGRAM_BOT_TOKEN_MAC_M1",
    "win11": "TELEGRAM_BOT_TOKEN_WIN11",
}

AGENT_ROLES: tuple[str, ...] = ("mac-m4", "mac-m1", "win11")

TOPIC_ENV: dict[str, str] = {
    "mail": "TELEGRAM_TOPIC_MAIL",
    "mac-m4": "TELEGRAM_TOPIC_MAC_M4",
    "mac-m1": "TELEGRAM_TOPIC_MAC_M1",
    "win11": "TELEGRAM_TOPIC_WIN11",
}

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ID_SPLIT_RE = re.compile(r"[\s,]+")


@dataclass(frozen=True)
class Settings:
    tokens: dict[str, str]
    group_id: int | None
    topics: dict[str, int]
    allowed_user_ids: tuple[int, ...]

    def __repr__(self) -> str:
        filled = [role for role, value in self.tokens.items() if value]
        return (
            f"Settings(tokens_set={filled}, group_id={self.group_id}, "
            f"topics={self.topics}, allowed_user_ids={self.allowed_user_ids})"
        )

    def require_users(self) -> None:
        if not self.allowed_user_ids:
            raise SystemExit("TELEGRAM_ALLOWED_USER_IDS gerekli. Kurulum için id-helper kullanın.")

    def permits(self, chat_id: int, user_id: int) -> bool:
        return self.group_id == chat_id and user_id in self.allowed_user_ids

    def token(self, role: str) -> str:
        env_name = ROLE_TOKEN_ENV[role]
        value = self.tokens.get(role, "")
        if not value:
            raise SystemExit(
                f"Eksik: {env_name}\n"
                "Bu anahtarı .env dosyasına yazın. Şablon: .env.example\n"
                "Tokenı komut satırına yazmayın."
            )
        return value


def project_root() -> Path:
    here = Path(__file__).resolve().parent
    for directory in (here, *here.parents):
        if (directory / "pyproject.toml").is_file() and (directory / "src" / "bildirim").is_dir():
            return directory
    return Path.cwd()


def load_settings() -> Settings:
    _load_env_file(project_root() / ".env")
    tokens = {
        role: _clean(os.environ.get(env_name))
        for role, env_name in ROLE_TOKEN_ENV.items()
    }
    topics: dict[str, int] = {}
    for role, env_name in TOPIC_ENV.items():
        raw = _clean(os.environ.get(env_name))
        if raw:
            topics[role] = _parse_int(env_name, raw)
    group_raw = _clean(os.environ.get("TELEGRAM_GROUP_ID"))
    group_id = _parse_int("TELEGRAM_GROUP_ID", group_raw) if group_raw else None
    allowed = _parse_id_list(os.environ.get("TELEGRAM_ALLOWED_USER_IDS"))
    return Settings(
        tokens=tokens,
        group_id=group_id,
        topics=topics,
        allowed_user_ids=allowed,
    )


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _KEY_RE.fullmatch(key):
            continue
        cleaned = _strip_value(value.strip())
        if cleaned:
            parsed[key] = cleaned
    for key, value in parsed.items():
        if not os.environ.get(key):
            os.environ[key] = value


def _strip_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    comment = value.find(" #")
    if comment != -1:
        return value[:comment].rstrip()
    return value


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw, 10)
    except ValueError:
        shown = "(gizlendi)" if ":" in raw or len(raw) > 32 else raw
        raise SystemExit(f"{name} tam sayı olmalı. Yazılan değer: {shown}") from None


def _parse_id_list(raw: str | None) -> tuple[int, ...]:
    cleaned = _clean(raw)
    if not cleaned:
        return ()
    found: list[int] = []
    for part in _ID_SPLIT_RE.split(cleaned):
        if not part:
            continue
        found.append(_parse_int("TELEGRAM_ALLOWED_USER_IDS", part))
    return tuple(dict.fromkeys(found))


def project_setting(name: str, default: str = "") -> str:
    """Resolve a Seyir option, including settings from earlier installations."""
    return (
        _clean(os.environ.get(f"SEYIR_{name}"))
        or _clean(os.environ.get(f"BILDIRIM_{name}"))
        or default
    )


def bridge_secret() -> str:
    configured = project_setting("BRIDGE_SECRET")
    if configured:
        return configured
    path = project_root() / "data" / "bridge.secret"
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    raise SystemExit("Cursor bağlantısı için önce python scripts/install-hooks.py çalıştırın.")
