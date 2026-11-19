"""Markdown-ish text → Telegram HTML (parse_mode=HTML)."""

from __future__ import annotations

import re
from typing import Any

_SECTION_TITLES = {
    "şu an ne yapıyor",
    "son adımlar",
    "risk/blokaj",
    "risk / blokaj",
    "sırada ne olabilir",
}


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def to_telegram_html(text: str, *, header: str | None = None) -> str:
    """Convert light markdown / plain sections to Telegram HTML."""
    out: list[str] = []
    if header:
        first = header.splitlines()[0].strip()
        if first:
            out.append(f"<b>{escape_html(first)}</b>")
        for ln in header.splitlines()[1:]:
            if ln.strip():
                out.append(f"<i>{escape_html(ln.strip())}</i>")
                out.append("")
                break

    body = text or ""
    in_code = False
    code_buf: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                out.append("<pre>" + escape_html("\n".join(code_buf)) + "</pre>")
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            out.append(f"<b>{_inline_md(escape_html(title))}</b>")
            continue
        low = stripped.rstrip(":").lower()
        if low in _SECTION_TITLES:
            out.append(f"<b>{escape_html(stripped.rstrip(':'))}</b>")
            continue
        if stripped.startswith(("- ", "* ", "• ")):
            item = stripped[2:].strip()
            out.append(f"• {_inline_md(escape_html(item))}")
            continue
        out.append(_inline_md(escape_html(line)))
    if in_code and code_buf:
        out.append("<pre>" + escape_html("\n".join(code_buf)) + "</pre>")
    return "\n".join(out)[:3900]


def _inline_md(escaped: str) -> str:
    def bold(m: Any) -> str:
        return f"<b>{m.group(1)}</b>"

    def code(m: Any) -> str:
        return f"<code>{m.group(1)}</code>"

    escaped = re.sub(r"\*\*(.+?)\*\*", bold, escaped)
    escaped = re.sub(r"`([^`]+)`", code, escaped)
    return escaped
