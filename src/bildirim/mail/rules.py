"""Deterministic noise / meeting hints before calling Qwen."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

NOISE_DOMAIN_MARKERS: tuple[str, ...] = (
    "bitbucket.org",
    "atlassian.net",
    "mail.cursor.com",
    "github.com",
    "notifications.github.com",
)

NOISE_ADDRESS_MARKERS: tuple[str, ...] = (
    "pullrequests-reply@",
    "notifications-noreply@",
    "confluence@",
    "jira@",
    "code-review@",
)

NOISE_SUBJECT_MARKERS: tuple[str, ...] = (
    "[bitbucket]",
    "pull request #",
    "ssh key added",
)

MEETING_SUBJECT_HINTS: tuple[str, ...] = (
    "toplantı",
    "toplanti",
    "meeting",
    "invite",
    "davet",
    "teams meeting",
    "zoom",
)

# RSVP noise, not the invite itself
RSVP_SUBJECT = re.compile(
    r"^(accepted|declined|tentative|kabul edildi|reddedildi)\s*:",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MailItem:
    message_id: str
    subject: str
    sender: str
    date_received: str
    body: str
    unread: bool


def sender_address(sender: str) -> str:
    match = re.search(r"<([^>]+)>", sender)
    if match:
        return match.group(1).strip().lower()
    return sender.strip().lower()


def sender_domain(sender: str) -> str:
    addr = sender_address(sender)
    if "@" not in addr:
        return ""
    return addr.rsplit("@", 1)[-1]


def is_noise(item: MailItem) -> bool:
    subject = item.subject.lower()
    sender = item.sender.lower()
    addr = sender_address(item.sender)
    domain = sender_domain(item.sender)

    if RSVP_SUBJECT.match(item.subject.strip()):
        return True
    if any(m in domain for m in NOISE_DOMAIN_MARKERS):
        return True
    if any(m in addr or m in sender for m in NOISE_ADDRESS_MARKERS):
        return True
    if any(m in subject for m in NOISE_SUBJECT_MARKERS):
        return True
    if "meetsense" in subject and "paylaşıma açtı" in subject:
        return True
    if "meetsense" in subject and "paylasima acti" in subject:
        return True
    return False


def looks_like_calendar(item: MailItem) -> bool:
    body = item.body.upper()
    if "BEGIN:VCALENDAR" in body or "TEXT/CALENDAR" in body:
        return True
    subject = item.subject.lower()
    if RSVP_SUBJECT.match(item.subject.strip()):
        return False
    return any(h in subject for h in MEETING_SUBJECT_HINTS)


def is_external(item: MailItem) -> bool:
    domain = sender_domain(item.sender)
    if not domain:
        return False
    internal = os.environ.get("MAIL_INTERNAL_DOMAINS", "").lower().split(",")
    if domain in {entry.strip() for entry in internal}:
        return False
    if any(m in domain for m in NOISE_DOMAIN_MARKERS):
        return False
    return True
