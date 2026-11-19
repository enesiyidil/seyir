"""CLI: seyir mail | agent --role mac-m4 | id-helper"""

from __future__ import annotations

import argparse

from bildirim.bots.agent_bot import run as run_agent
from bildirim.bots.id_helper import run as run_id_helper
from bildirim.bots.mail_bot import run as run_mail
from bildirim.config import AGENT_ROLES, ROLE_TOKEN_ENV, load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="seyir",
        description="Access Apple Mail, Cursor sessions, and your Mac desktop through Telegram.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "mail",
        help="Start the mail bot and watch Apple Mail with local Qwen.",
    )
    once = sub.add_parser(
        "mail-once",
        help="Scan the inbox once and exit.",
    )

    agent = sub.add_parser(
        "agent",
        help="Start the Mac desktop and Cursor bot (mac-m4), or a ping-only role.",
    )
    agent.add_argument("--role", required=True, choices=AGENT_ROLES)

    helper = sub.add_parser("id-helper", help="Show the Telegram group, topic, and user IDs for setup.")
    helper.add_argument(
        "--role",
        default="mail",
        choices=tuple(ROLE_TOKEN_ENV),
        help="Bot role to listen with (default: mail).",
    )

    sub.add_parser(
        "cursor-auth",
        help="Save a supplied Cursor session token locally for usage queries.",
    )
    sub.add_parser(
        "limit",
        help="Print the Cursor usage summary (also available as /limit in Telegram).",
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
        print(f"New messages processed: {count}")
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
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
