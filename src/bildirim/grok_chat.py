"""Multi-turn Grok chat for Telegram topics (meta + session) with ACTIONS."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from bildirim.cursor_agent_cli import cursor_agent_ask
from bildirim.cursor_sessions import SessionStore
from bildirim.cursor_trace import evidence_text
from bildirim.cursor_usage import fetch_usage_summary
from bildirim.grok_model import resolve_top_grok
from bildirim.grok_summary import summarize_session
from bildirim.ide_send import send_to_ide
from bildirim.ide_stream import start_stream, stop_stream
from bildirim.telegram_format import escape_html, to_telegram_html
from bildirim.topic_memory import append_turn, format_history

META_OPS = frozenset({"oturumlar", "limit", "dur", "devam", "ozet", "yaz", "ekran", "ekran_dur"})
SESSION_OPS = frozenset({"dur", "devam", "ozet", "yaz", "ekran", "ekran_dur"})


@dataclass(frozen=True)
class ChatResult:
    ok: bool
    text: str
    html: str
    model: str
    actions_note: str = ""


def handle_topic_message(
    store: SessionStore,
    *,
    topic_id: int,
    user_text: str,
    mode: str,
    conversation_id: str | None = None,
    image_path: str = "",
) -> ChatResult:
    """mode: 'meta' | 'session'."""
    store.reload()
    model = resolve_top_grok()
    append_turn(topic_id, "user", user_text, mode=mode)

    if mode == "meta":
        context = _meta_context(store)
        allowed = META_OPS
        bound_cid = None
    else:
        cid = conversation_id
        meta = store.get(cid) if cid else None
        if cid is None or meta is None:
            found = store.find_by_topic(topic_id)
            if found:
                cid, meta = found
        if cid is None or meta is None:
            msg = "Bu konu bir IDE oturumuna bağlı değil."
            append_turn(topic_id, "assistant", msg, mode=mode)
            return ChatResult(ok=False, text=msg, html=escape_html(msg), model=model)
        context = _session_context(cid, meta)
        allowed = SESSION_OPS
        bound_cid = cid

    history = format_history(topic_id, limit=30)
    image_note = ""
    if image_path:
        image_note = (
            "Kullanıcı bir görüntü gönderdi. İlk işin bu dosyayı açıp görüntüyü incelemek:\n"
            f"{image_path}\n"
            "Görüntüdeki sorunu çözmek için uygun ACTIONS üret. "
            "Görüntüyü görmeden tahmin yürütme.\n\n"
        )
    prompt = _build_prompt(
        mode=mode,
        context=context,
        history=history,
        user_text=user_text,
        allowed=sorted(allowed),
        image_note=image_note,
    )
    raw, err = cursor_agent_ask(prompt, model=model, timeout=180)
    if not raw:
        msg = f"Grok cevap veremedi ({err})."
        append_turn(topic_id, "assistant", msg, mode=mode)
        return ChatResult(ok=False, text=msg, html=escape_html(msg), model=model)

    reply_text, actions = _parse_reply_actions(raw)
    if not reply_text:
        reply_text = raw.strip()

    notes = _run_actions(
        store,
        actions,
        allowed=allowed,
        bound_conversation_id=bound_cid,
        topic_id=topic_id,
        mode=mode,
    )
    if notes:
        reply_text = "\n".join(notes) + "\n\n" + reply_text.rstrip()

    header = f"Grok · {mode}\nModel: {model}\n"
    full = header + reply_text
    html = to_telegram_html(reply_text, header=f"Grok · {mode}\nModel: {model}")
    memory_text = re.sub(r"(https://[^\s]+/\?t=)[\w-]+", "[ekran bağlantısı]", reply_text)
    append_turn(topic_id, "assistant", memory_text, mode=mode)
    return ChatResult(
        ok=True,
        text=full,
        html=html,
        model=model,
        actions_note="\n".join(notes),
    )


def _meta_context(store: SessionStore) -> str:
    rows = store.list_recent(15)
    lines = [
        f"freeze_all={store.is_freeze_all()}",
        f"active_id={store.active()[0][:8] if store.active() else None}",
        "Oturumlar:",
    ]
    if not rows:
        lines.append("(yok)")
    for cid, meta in rows:
        flag = "STOP" if meta.get("stop_requested") else (
            "aktif" if meta.get("active", True) else "bitti"
        )
        lines.append(
            f"- {meta.get('short_id')} [{flag}] "
            f"{meta.get('project') or '?'} topic={meta.get('topic_id')} "
            f"last={str(meta.get('last_at') or '')[:19]}"
        )
    lines.append(
        "Komutlar: /ping /oturumlar /limit /dur [/id|/hepsi] "
        "/devam [/id|/hepsi] /ozet [/id]"
    )
    return "\n".join(lines)


def _session_context(cid: str, meta: dict[str, Any]) -> str:
    return (
        f"Bağlı IDE oturumu: short={meta.get('short_id')} project={meta.get('project')}\n"
        f"stop={meta.get('stop_requested')} active={meta.get('active')}\n"
        f"İzler:\n{evidence_text(cid, meta=meta)}"
    )


def _build_prompt(
    *,
    mode: str,
    context: str,
    history: str,
    user_text: str,
    allowed: list[str],
    image_note: str = "",
) -> str:
    role = (
        "Sen mac-m4 Telegram meta asistanısın. Tüm IDE oturumlarının farkındasın. "
        "Kullanıcı doğal dilde isterse ACTIONS ile gerçek işlem yap."
        if mode == "meta"
        else "Sen bu Telegram konusundaki IDE agent için yan asistanısın. "
        "Yalnızca bağlı oturumu bilirsin; durum, kalan iş, risk sorularına cevap ver. "
        "Gerekirse yalnız bu oturum için dur/devam/ozet ACTION üret."
    )
    return (
        f"{role}\n"
        "Türkçe yaz. Telegram'da okunaklı ol: kısa başlıklar, • maddeler. "
        "Ağır markdown kullanma (tablolar yok).\n"
        "Cevabı TAM olarak şu formatta ver:\n"
        "REPLY:\n"
        "<kullanıcıya gidecek metin>\n"
        "ACTIONS:\n"
        "<JSON dizi; işlem yoksa []>\n"
        f"İzinli op'lar: {', '.join(allowed)}\n"
        'Örnek: [{"op":"dur","target":"hepsi"}] veya '
        '[{"op":"ozet","target":"a1b2c3d4"}] veya '
        '[{"op":"yaz","text":"devam et, onaylıyorum"}] veya '
        '[{"op":"ekran"}] veya [{"op":"ekran_dur"}]\n'
        "target: short_id, hepsi, veya boş.\n"
        "Kullanıcı IDE'deki agenta bir şey yazdırmak, sorusunu cevaplamak, "
        "onay vermek veya devam ettirmek isterse op yaz kullan. "
        "Metni text alanına koy. Yazının gidip gitmediğini söyleme; sistem sonucu ayrıca ekler.\n"
        "Canlı IDE görüntüsü istenirse op ekran. Durdurmak için ekran_dur.\n\n"
        f"--- BAĞLAM ---\n{context}\n\n"
        f"--- KONU GEÇMİŞİ ---\n{history}\n\n"
        f"{image_note}"
        f"--- YENİ MESAJ ---\n{user_text}\n"
    )


def _parse_reply_actions(raw: str) -> tuple[str, list[dict[str, Any]]]:
    text = raw.strip()
    # Normalize
    reply = text
    actions: list[dict[str, Any]] = []

    m_reply = re.search(
        r"(?is)^\s*REPLY:\s*(.*?)\s*(?=ACTIONS:|\Z)", text
    )
    m_actions = re.search(r"(?is)ACTIONS:\s*(.*)\Z", text)

    if m_reply:
        reply = m_reply.group(1).strip()
    if m_actions:
        blob = m_actions.group(1).strip()
        # strip fences
        if blob.startswith("```"):
            blob = re.sub(r"^```(?:json)?\s*", "", blob)
            blob = re.sub(r"\s*```$", "", blob)
        try:
            parsed = json.loads(blob)
            if isinstance(parsed, list):
                actions = [a for a in parsed if isinstance(a, dict)]
            elif isinstance(parsed, dict):
                actions = [parsed]
        except json.JSONDecodeError:
            # try find first [...]
            m = re.search(r"\[.*\]", blob, re.S)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                    if isinstance(parsed, list):
                        actions = [a for a in parsed if isinstance(a, dict)]
                except json.JSONDecodeError:
                    actions = []
    elif not m_reply:
        # Model ignored format — whole text is reply
        reply = text
        actions = []

    return reply, actions


def _run_actions(
    store: SessionStore,
    actions: list[dict[str, Any]],
    *,
    allowed: frozenset[str],
    bound_conversation_id: str | None,
    topic_id: int,
    mode: str,
) -> list[str]:
    notes: list[str] = []
    for action in actions[:5]:
        op = str(action.get("op") or "").strip().lower()
        if op not in allowed:
            notes.append(f"• Atlandı (izin yok): {op or '?'}")
            continue
        target = action.get("target")
        target_s = "" if target is None else str(target).strip()

        if op == "oturumlar":
            rows = store.list_recent(12)
            if not rows:
                notes.append("• Oturum yok.")
            else:
                lines = ["• Oturumlar:"]
                for cid, meta in rows:
                    flag = "STOP" if meta.get("stop_requested") else (
                        "aktif" if meta.get("active", True) else "bitti"
                    )
                    lines.append(
                        f"  - {meta.get('short_id')} [{flag}] "
                        f"{meta.get('project') or '?'}"
                    )
                notes.append("\n".join(lines))
            continue

        if op == "limit":
            summary = fetch_usage_summary()
            notes.append("• Limit:\n" + summary.text[:1500])
            continue

        if op == "dur":
            note = _action_dur(store, target_s, bound_conversation_id, mode)
            notes.append(note)
            continue

        if op == "devam":
            note = _action_devam(store, target_s, bound_conversation_id, mode)
            notes.append(note)
            continue

        if op == "ozet":
            note = _action_ozet(store, target_s, bound_conversation_id, mode)
            notes.append(note)
            continue

        if op == "yaz":
            text = str(action.get("text") or "").strip()
            notes.append(
                _action_yaz(store, text, target_s, bound_conversation_id, mode)
            )
            continue

        if op == "ekran":
            notes.append(_action_ekran(store, target_s, bound_conversation_id, mode, topic_id))
            continue

        if op == "ekran_dur":
            notes.append("• " + stop_stream().text)
            continue

    return notes


def _action_dur(
    store: SessionStore,
    target: str,
    bound: str | None,
    mode: str,
) -> str:
    store.reload()
    t = target.lower()
    if mode == "session":
        if not bound:
            return "• dur: bağlı oturum yok."
        store.set_stop(bound, True)
        meta = store.get(bound) or {}
        return f"• Durduruldu: {meta.get('short_id') or bound[:8]}"
    if t in {"hepsi", "all", "*"}:
        n = len(store.stop_all_active())
        return f"• Durdurma: tümü kilitlendi ({n})."
    cid, meta = _resolve_target(store, target, bound)
    if not cid or not meta:
        return "• dur: oturum bulunamadı."
    store.set_stop(cid, True)
    return f"• Durduruldu: {meta.get('short_id')}"


def _action_devam(
    store: SessionStore,
    target: str,
    bound: str | None,
    mode: str,
) -> str:
    store.reload()
    t = target.lower()
    if mode == "session":
        if not bound:
            return "• devam: bağlı oturum yok."
        store.clear_stop(bound)
        meta = store.get(bound) or {}
        return f"• Devam: {meta.get('short_id') or bound[:8]}"
    if t in {"hepsi", "all", "*"} or store.is_freeze_all():
        store.set_freeze_all(False)
        for cid, _ in store.list_recent(50):
            store.clear_stop(cid)
        return "• Devam: tüm kilitler kalktı."
    cid, meta = _resolve_target(store, target, bound)
    if not cid or not meta:
        return "• devam: oturum bulunamadı."
    store.clear_stop(cid)
    return f"• Devam: {meta.get('short_id')}"


def _action_ozet(
    store: SessionStore,
    target: str,
    bound: str | None,
    mode: str,
) -> str:
    cid: str | None = None
    if mode == "session":
        cid = bound
    else:
        found_cid, _meta = _resolve_target(store, target, bound)
        cid = found_cid
    if not cid:
        return "• ozet: oturum yok."
    result = summarize_session(store, conversation_id=cid)
    body = result.text[:2000]
    return "• Özet:\n" + body


def _project_for(
    store: SessionStore,
    target: str,
    bound: str | None,
    mode: str,
) -> tuple[str | None, str]:
    if mode == "session" and bound:
        meta = store.get(bound) or {}
        return bound, str(meta.get("project") or "")
    cid, meta = _resolve_target(store, target, bound)
    if not cid or not meta:
        return None, ""
    return cid, str(meta.get("project") or "")


def _action_yaz(
    store: SessionStore,
    text: str,
    target: str,
    bound: str | None,
    mode: str,
) -> str:
    if not text:
        return "• yaz: metin yok."
    _cid, project = _project_for(store, target, bound, mode)
    result = send_to_ide(text, project=project)
    return "• " + result.text


def _action_ekran(
    store: SessionStore,
    target: str,
    bound: str | None,
    mode: str,
    topic_id: int,
) -> str:
    if mode == "meta" and not target:
        return "• " + start_stream(mode="desktop", topic_id=topic_id).text
    cid, project = _project_for(store, target, bound, mode)
    if not cid:
        return "• Cursor oturumu bulunamadı."
    meta = store.get(cid) or {}
    result = start_stream(mode="window", project=project, conversation_id=cid,
                          topic_id=topic_id, short_id=str(meta.get("short_id") or ""))
    return "• " + result.text


def _resolve_target(
    store: SessionStore,
    target: str,
    bound: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    if target:
        found = store.find_by_short(target)
        if found:
            return found
    if bound:
        meta = store.get(bound)
        return (bound, meta) if meta else (None, None)
    found = store.active()
    return found if found else (None, None)
