"""Local Turkish commands for the desktop voice bridge."""

from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from bildirim import desktop_control as desk
from bildirim.config import project_root

_CODEX = "com.openai.codex"
_CURSOR = "com.todesktop.230313mzl4w4u92"
_TEAMS = "com.microsoft.teams2"
_ALIASES = {
    _CODEX: (
        "codex",
        "koldex",
        "koldeks",
        "kodeks",
        "kod eks",
        "kod ex",
        "code x",
        "kode x",
        "kodex",
    ),
    _CURSOR: ("cursor", "kursor", "ajan", "agent"),
    _TEAMS: ("microsoft teams", "teams", "tims", "timiz"),
}
_TRANSLATE = str.maketrans(
    {
        "Ç": "c",
        "ç": "c",
        "Ğ": "g",
        "ğ": "g",
        "İ": "i",
        "I": "i",
        "ı": "i",
        "Ö": "o",
        "ö": "o",
        "Ş": "s",
        "ş": "s",
        "Ü": "u",
        "ü": "u",
        "’": "'",
    }
)
_BUILD = threading.Lock()


def fold(text: str) -> str:
    # Preserve character positions so dictation is always copied from the original.
    return text.translate(_TRANSLATE).lower()


def native(**request: str) -> dict:
    root = project_root() / "scripts"
    source, binary = root / "voice_input.swift", root / "bin" / "voice-input"
    with _BUILD:
        if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
            binary.parent.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(dir=binary.parent) as temp:
                built = Path(temp) / "voice-input"
                subprocess.run(
                    ["swiftc", "-O", str(source), "-o", str(built)],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
                os.replace(built, binary)
    proc = subprocess.run(
        [str(binary)],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=True,
        timeout=18,
    )
    return json.loads(proc.stdout)


def application_context() -> tuple[list[dict], str]:
    state = native(op="apps")
    return state["apps"], state["front"]


def _app_prefix(text: str, apps: list[dict]) -> tuple[str, int] | None:
    # Turkish speech recognition alternates c/k, d/t and x/ks for "Codex".
    # Match only the complete app name (with its spoken case ending).
    codex = re.match(
        r"(?:co|ko)l?\s*[dt]\s*(?:e(?:ks|x)|x)(?:\s*'\s*|\s*)"
        r"(?:ten|den|te|de|e|a|i)?(?=\s|[:,]|$)",
        text,
    )
    if codex:
        return _CODEX, codex.end()
    candidates = [(fold(a["name"]), a["id"]) for a in apps]
    candidates.extend(
        (alias, bundle) for bundle, names in _ALIASES.items() for alias in names
    )
    for name, bundle in sorted(candidates, key=lambda x: -len(x[0])):
        m = re.match(
            re.escape(name)
            + r"(?:\s*'\s*|(?=\s+[ae]\b)|)(?:den|dan|ten|tan|nin|nun|in|un|ya|ye|na|ne|da|de|ta|te|yi|yu|i|u|a|e)?(?=\s|[:,]|$)",
            text,
        )
        if m:
            end = m.end()
            suffix = re.match(r"\s+[ae](?=\s)", text[end:])
            return bundle, end + (suffix.end() if suffix else 0)
    return None


def _switch_space(direction: str) -> str:
    right = direction == "sag"
    code, flags = (124 if right else 123), 1 << 18
    try:
        prefs = subprocess.check_output(
            ["defaults", "export", "com.apple.symbolichotkeys", "-"], timeout=1
        )
        shortcut = plistlib.loads(prefs)["AppleSymbolicHotKeys"].get(
            "81" if right else "79", {}
        )
        if shortcut.get("enabled") is False:
            return "Mission Control ayarlarında bu yöndeki masaüstü kısayolu kapalı."
        params = shortcut.get("value", {}).get("parameters", [])
        if len(params) == 3 and 0 <= params[1] < 128:
            code, flags = int(params[1]), int(params[2])
    except (OSError, KeyError, ValueError, subprocess.SubprocessError):
        pass
    result = native(op="space", key=str(code), flags=str(flags))
    if result.get("error"):
        return result["error"]
    if result.get("changed"):
        return "Sağ masaüstüne geçildi." if right else "Sol masaüstüne geçildi."
    return "Mac masaüstü değişikliği bildirmedi. Bu yönde başka alan olmayabilir."


def _movement(command: str, mode: str) -> str | None:
    m = re.fullmatch(
        r"(?:(ekrani?|masaustunu|sayfayi|icerigi) )?(saga|sola|yukari|asagi) kaydir",
        command,
    )
    space = re.fullmatch(
        r"(sag|sol)(?:daki)? (?:masaustune|ekrana) (?:gec|git)", command
    )
    if space or (
        m
        and mode == "desktop"
        and m[2] in ("saga", "sola")
        and m[1] not in ("sayfayi", "icerigi")
    ):
        if mode != "desktop":
            return "Masaüstünü değiştirmek için Mac-M4 konusunu aç."
        return _switch_space(space[1] if space else m[2][:-1])
    if m:
        dx, dy = {"saga": (6, 0), "sola": (-6, 0), "yukari": (0, 6), "asagi": (0, -6)}[
            m[2]
        ]
        desk.require_input()
        desk.scroll(dx=dx, dy=dy)
        return "Sayfaya kaydırma girdisi iletildi."
    if mode != "desktop":
        return None
    key = re.fullmatch(
        r"(enter|return|esc|escape|tab|sil|backspace|bosluk|sag ok|sol ok|asagi ok|yukari ok)(?:[ '\w]*? bas)?",
        command,
    )
    if key:
        codes = {
            "enter": 36,
            "return": 36,
            "esc": 53,
            "escape": 53,
            "tab": 48,
            "sil": 51,
            "backspace": 51,
            "bosluk": 49,
            "sag ok": 124,
            "sol ok": 123,
            "asagi ok": 125,
            "yukari ok": 126,
        }
        desk.key_chord(codes[key[1]])
        return "Tuş iletildi."
    chords = {"kopyala": 8, "yapistir": 9, "tumunu sec": 0, "geri al": 6}
    if command in chords:
        desk.key_chord(chords[command], 1 << 20)
        return "Kısayol iletildi."
    pointer = re.fullmatch(
        r"(?:fareyi|imleci|mouse'u|mouseu|mausu) (saga|sola|asagi|yukari)(?: (\d{1,4})(?: piksel)?)? (?:gotur|tasi|kaydir|hareket ettir)",
        command,
    )
    clicks = {
        "tikla": "click",
        "buraya tikla": "click",
        "sag tikla": "right",
        "cift tikla": "double",
    }
    if pointer or command in clicks:
        desk.pointer_command(
            clicks.get(command, "move"),
            pointer[1] if pointer else "",
            int(pointer[2] or 60) if pointer else 0,
        )
        return "Fare girdisi iletildi."
    return None


def _writing(text: str) -> tuple[str, str, bool] | None:
    """Return the addressing phrase, literal dictation, and explicit submit intent."""
    low = fold(text)
    # Markers separate who to write to from text that may itself contain verbs.
    marker = re.search(
        r"\b(?:(?:su (?:komutu|metni|mesaji)|sunu|mesaj(?:i)?|sunlari) )?yaz(?:in|ar misin|abilir misin)?\b\s*[:;,]?\s+",
        low,
    )
    if marker and not re.fullmatch(
        r"(?:ve (?:gonder|yolla)|ama gonderme)[.!]?", low[marker.end() :]
    ):
        address = text[: marker.start()].strip()
        body = text[marker.end() :].strip()
        body = re.sub(r"^ama g[öo]nderme\s*[:,]\s*", "", body, flags=re.IGNORECASE)
        return address, body, False
    ending = re.search(
        r"\s+(?:(?:diye|seklinde)(?: bir)?(?: mesaj)?\s+)?(?:yazip (?:gonder|yolla)|yaz(?:in|ar misin|abilir misin)?(?: (?:ve (?:gonder|yolla)|ama gonderme))?)[.?!]?$",
        low,
    )
    if ending:
        return (
            text[: ending.start()].strip(),
            "",
            ("gonder" in ending[0] or "yolla" in ending[0])
            and "gonderme" not in ending[0],
        )
    return None


def _input_result(**args: str) -> str:
    result = native(**args)
    return result.get("error") or result["reply"]


@dataclass
class TeamsDraft:
    step: str = ""
    recipient: str = ""
    body: str = ""
    until: float = 0
    codex_receipt: str = ""

    def ask(self, step: str, recipient: str = "", body: str = "") -> None:
        self.step, self.recipient, self.body = step, recipient, body
        self.until = time.monotonic() + 90


def _teams_write(
    recipient: str, body: str, submit: bool, dialog: TeamsDraft | None
) -> str:
    result = native(
        op="write",
        id=_TEAMS,
        field="composer",
        text=body,
        recipient=recipient,
        submit="yes" if submit else "no",
    )
    if result.get("code") == "recipient" and dialog is not None:
        dialog.ask("recipient", body=body)
    return result.get("error") or result["reply"]


def _followup(dialog: TeamsDraft, phrase: str, apps: list[dict]) -> str | None:
    if not dialog.step or time.monotonic() > dialog.until:
        dialog.step = ""
        return None
    step, person, message = dialog.step, dialog.recipient, dialog.body
    dialog.step = ""
    low = fold(phrase).strip(" .!?")
    if low in {"iptal", "vazgec", "bos ver", "vazgectim"}:
        return "Teams taslağı iptal edildi."
    if low in {"gonder", "mesaji gonder", "taslagi gonder"}:
        dialog.ask(step, person, message)
        return "Önce Teams taslağını tamamla veya vazgeç."
    if (
        _app_prefix(low, apps)
        or low == "hangi uygulamalar acik"
        or re.fullmatch(r"(ekrani|sayfayi) \w+ kaydir", low)
    ):
        return None
    if step == "recipient":
        if not re.fullmatch(r"[\w.+@'-]+(?: [\w.'-]+){0,5}", phrase.strip()):
            dialog.ask("recipient", body=message)
            return "Alıcının ad soyadını veya e-postasını söyle."
        person = phrase.strip()
        if not message:
            dialog.ask("text", recipient=person)
            return person + " için ne yazayım?"
    else:
        message = phrase
    return _teams_write(person, message, False, dialog)


def local_command(
    phrase: str,
    session: dict,
    apps: list[dict],
    front: str,
    dialog: TeamsDraft | None = None,
) -> str | None:
    mode = session.get("mode", "window")
    if dialog is not None and mode == "desktop":
        answer = _followup(dialog, phrase, apps)
        if answer is not None:
            return answer
    low = fold(phrase).strip(" .!?")
    motion = _movement(low, mode)
    if motion:
        return motion
    if re.fullmatch(
        r"(?:acik uygulamalari (?:say|listele|goster)|(?:(?:su an|macte|mac\x27te) )*hangi uygulamalar acik|acik (?:olan )?uygulamalar(?: neler)?)",
        low,
    ):
        return "Açık uygulamalar: " + ", ".join(
            a["name"] + (" (önde)" if a["id"] == front else "") for a in apps
        )
    text = re.sub(r"^(?:(?:ekrandaki|lutfen|su an acik olan)\s+)+", "", fold(phrase))
    offset = len(phrase) - len(text)
    original = phrase[offset:]
    writing = _writing(original)
    target_text = writing[0] if writing else original
    app = _app_prefix(fold(target_text), apps)
    app_id = app[0] if app else ""
    rest = target_text[app[1] :].strip(" ,:") if app else target_text
    if app and mode == "window" and app_id != _CURSOR:
        return "Bu işlem için Mac-M4 konusunu aç."
    if (
        app
        and not writing
        and fold(rest).strip(" .!?")
        in {"gec", "git", "ac", "one getir", "uygulamasina gec"}
    ):
        return _input_result(op="activate", id=app_id)
    if not writing:
        if low in {"gonder", "mesaji gonder", "taslagi gonder"}:
            if front not in (_TEAMS, _CODEX, _CURSOR) or (
                mode == "window" and front != _CURSOR
            ):
                return "Gönderilecek sohbeti öne al."
            receipt = (
                dialog.codex_receipt if front == _CODEX and dialog is not None else ""
            )
            if dialog is not None:
                dialog.codex_receipt = ""
            return _input_result(
                op="send",
                id=front,
                receipt=receipt,
                project=str(session.get("project") or "") if mode == "window" else "",
            )
        return None
    _, body, submit = writing
    recipient = ""
    if app_id == _TEAMS:
        if fold(rest).strip(" ,:") in {
            "",
            "birine",
            "birisine",
            "birine mesaj",
            "birine bir mesaj",
            "bir kisiye mesaj",
        }:
            if dialog is not None:
                dialog.ask("recipient", body=body)
            return "Teams’te kime yazayım? Ad soyad veya e-posta söyle."
        if rest:
            # In spoken Turkish a proper name may arrive with a separate or attached apostrophe.
            person = re.match(r"(.{1,90}?)(?:'\s*|’\s*|\s+)(?:ya|ye|a|e)\b", fold(rest))
            email = re.match(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}(?=['’\s:,]|$)", fold(rest))
            if email:
                recipient = rest[: email.end()]
                rest = re.sub(
                    r"^['’](?:ya|ye|a|e)\b",
                    "",
                    rest[email.end() :],
                    flags=re.IGNORECASE,
                ).strip(" ,:")
            elif person:
                recipient = rest[: person.end(1)].strip()
                rest = rest[person.end() :].strip(" ,:")
            elif body:
                recipient = rest.strip()
                rest = ""
            else:
                return "Teams’te alıcıyı ve mesajı ayırmak için “Teams’ten Ayşe Yılmaz’a şunu yaz: merhaba” de."
        if not recipient:
            return (
                "Teams’te kime yazayım? Ad soyad veya e-posta ile komutu tekrar söyle."
            )
    if not body:
        body = "" if fold(rest) in {"bir mesaj", "mesaj", "bir ileti", "sunu"} else rest
        body = re.sub(
            r"^(?:buraya|şunu|şöyle|mesaj olarak|mesaj kutusuna)\s+",
            "",
            body,
            flags=re.IGNORECASE,
        )
    elif (
        rest
        and app_id != _TEAMS
        and fold(rest)
        not in {"buraya", "sohbete", "sohbetine", "mesaj kutusuna", "komut satirina"}
    ):
        return "Hedefi ayırt edemedim. Uygulama adını söyleyip “şunu yaz” de."
    if not app and not original.lower().startswith(
        ("buraya ", "şunu yaz", "yaz ", "yaz:", "şöyle yaz")
    ):
        return "Nereye yazayım? Uygulama adını veya “buraya” de."
    if mode == "window":
        if not app_id and front != _CURSOR:
            return "Öndeki uygulama bu Cursor oturumu değil."
        app_id = _CURSOR
    app_id = app_id or front
    if not body.strip():
        if recipient and dialog is not None:
            dialog.ask("text", recipient=recipient)
        return (recipient + " için ne yazayım?") if recipient else "Ne yazayım?"
    if body.startswith(("“", '"', "«")) and body.endswith(("”", '"', "»")):
        body = body[1:-1]
    field = "composer" if app and app_id in (_CURSOR, _CODEX, _TEAMS) else "focused"
    if not app and mode == "desktop":
        field = "current"
    if submit and field != "composer":
        return "Gönderilecek sohbet uygulamasını belirt."
    if app_id == _TEAMS and recipient:
        return _teams_write(recipient, body, submit, dialog)
    result = native(
        op="write",
        id=app_id,
        field=field,
        recipient=recipient,
        text=body,
        submit="yes" if submit else "no",
        project=str(session.get("project") or "") if mode == "window" else "",
    )
    if dialog is not None and app_id == _CODEX:
        dialog.codex_receipt = result.get("receipt", "")
    return result.get("error") or result["reply"]


def natural_command(
    phrase: str, apps: list[dict], dialog: TeamsDraft | None
) -> str | None:
    """Resolve less regular draft requests locally. Keep message and identity literal."""
    low = fold(phrase)
    if not re.search(
        r"\b(?:hazirla(?:r misin|mani|yabilir misin)?|yazmani|yaziver|taslak olustur)\b",
        low,
    ):
        return None
    if re.search(r"\b(?:istemiyorum|gonderme disinda|yazma|hazirlama)\b", low):
        return None
    # Resolve app identity from the request before asking for its arguments.
    targets = set()
    for token in re.finditer(r"\b\w+", low):
        app = _app_prefix(low[token.start() :], apps)
        if app:
            targets.add(app[0])
    if len(targets) != 1:
        return "Taslak hangi uygulamaya yazılsın? Uygulama adını da söyle."
    target = targets.pop()
    if target not in {a["id"] for a in apps}:
        return "İstenen uygulama açık değil."
    from bildirim.mail.qwen import _model, _parse_json_content, _post_chat

    try:
        data = _post_chat(
            {
                "model": _model(),
                "temperature": 0,
                "max_tokens": 180,
                "response_format": {"type": "json_object"},
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            'Yalnız {"draft":true/false,"recipient":"","text":""} döndür. '
                            "Kullanıcı açıkça bir taslak istiyorsa draft true. Alıcı adını ve dikte edilen metni "
                            "kullanıcının sözlerinden aynen kopyala. Alıcının yönelme ekini alma. "
                            "Metin uydurma, eksik alanı boş bırak. Soru, olumsuz veya varsayımsal anlatımda draft false."
                        ),
                    },
                    {"role": "user", "content": phrase},
                ],
            },
            timeout=5,
        )
        result = _parse_json_content(data["choices"][0]["message"]["content"])
    except (
        SystemExit,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        RuntimeError,
        OSError,
    ):
        return "Taslağı ayıramadım. Uygulama adını söyleyip “şunu yaz” de."
    if result.get("draft") is not True:
        return None
    who, body = result.get("recipient"), result.get("text")
    if (
        not isinstance(body, str)
        or not isinstance(who, str)
        or body not in phrase
        or who not in phrase
    ):
        return (
            "Alıcıyı veya metni sözlerinde doğrulayamadım. “Şunu yaz” diyerek tekrarla."
        )
    if target == _TEAMS:
        if dialog is not None and not who:
            dialog.ask("recipient", body=body)
            return "Teams’te kime yazayım?"
        if dialog is not None and not body:
            dialog.ask("text", recipient=who)
            return who + " için ne yazayım?"
        if not who or not body:
            return "Teams için alıcıyı ve yazılacak metni birlikte söyle."
        return _teams_write(who, body, False, dialog)
    if not body:
        return "Taslakta ne yazsın?"
    result = native(
        op="write",
        id=target,
        field="composer" if target in {_CODEX, _CURSOR} else "focused",
        text=body,
        submit="no",
    )
    if target == _CODEX and dialog is not None:
        dialog.codex_receipt = result.get("receipt", "")
    return result.get("error") or result["reply"]
