"""CLI: python -m bildirim mail | agent --role mac-m4 | id-helper"""

from __future__ import annotations

import argparse

from bildirim.bots.agent_bot import run as run_agent
from bildirim.bots.id_helper import run as run_id_helper
from bildirim.bots.mail_bot import run as run_mail
from bildirim.config import AGENT_ROLES, ROLE_TOKEN_ENV, load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m bildirim",
        description="Telegram bildirim köprüsü.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "mail",
        help="E-posta botu + Exchange izleyici (Apple Mail → Qwen → Telegram).",
    )
    once = sub.add_parser(
        "mail-once",
        help="Gelen kutusunu bir kez tara, çık.",
    )

    agent = sub.add_parser(
        "agent",
        help="Bilgisayar botu. mac-m4: IDE mirror + /limit /dur /oturumlar; diğerleri /ping.",
    )
    agent.add_argument("--role", required=True, choices=AGENT_ROLES)

    helper = sub.add_parser("id-helper", help="Grup, konu ve kullanıcı numarasını yazdırır.")
    helper.add_argument(
        "--role",
        default="mail",
        choices=tuple(ROLE_TOKEN_ENV),
        help="Hangi botun tokenı ile dinlensin. Varsayılan: mail.",
    )

    sub.add_parser(
        "cursor-auth",
        help="Verdiğiniz Cursor oturum anahtarını yerel olarak kaydeder (/limit için).",
    )
    sub.add_parser(
        "limit",
        help="Cursor kullanım özetini yazdırır (Telegram /limit ile aynı).",
    )

    args = parser.parse_args(argv)
    settings = load_settings()
    if args.command == "mail":
        run_mail(settings)
        return
    if args.command == "mail-once":
        from bildirim.mail.store import ProcessedStore, default_path
        from bildirim.config import project_root
        from bildirim.mail.watcher import process_once

        token = settings.token("mail")
        store = ProcessedStore(default_path(project_root()))
        count = process_once(settings, store, token)
        print(f"İşlenen yeni mail: {count}")
        return
    if args.command == "agent":
        run_agent(settings, args.role)
        return
    if args.command == "id-helper":
        run_id_helper(settings, args.role)
        return
    if args.command == "cursor-auth":
        from bildirim.cursor_usage import save_session_interactive

        result = save_session_interactive()
        print(result.text)
        raise SystemExit(0 if result.ok else 1)
    if args.command == "limit":
        from bildirim.cursor_usage import fetch_usage_summary

        result = fetch_usage_summary()
        print(result.text)
        raise SystemExit(0 if result.ok else 1)
    raise SystemExit(f"Bilinmeyen komut: {args.command}")


if __name__ == "__main__":
    main()
