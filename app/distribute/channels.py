"""Digest delivery channels: email over SMTP and a Microsoft Teams channel.

A channel works once its settings are filled in (`.env` or the host's environment); until then
`status()` says it is not set up and the app offers "Copy as text" only. Nothing here is
specific to one company: the client brings its own mail server and its own Teams workflow.

- Email: any SMTP server (Microsoft 365, Gmail, SendGrid, an internal relay). A plain-text and
  an HTML part, to the comma-separated DIGEST_EMAIL_TO list.
- Teams: the URL of a "When a Teams webhook request is received" workflow (the Workflows app,
  which replaced the retired Office 365 connectors). The digest goes as an Adaptive Card.

Secrets (the SMTP password, the webhook URL) never leave this module: errors are redacted.
"""

from __future__ import annotations

import html
import json
import smtplib
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date
from email.message import EmailMessage
from typing import Any

from app.core.config import Settings, get_settings

CHANNELS = ("email", "teams")
MAX_ITEMS = 15  # rule changes listed in a sent digest; the rest are counted
TIMEOUT_S = 20

SmtpFactory = Callable[[Settings], Any]
Post = Callable[[str, bytes], int]


def _settings(s: Settings | None) -> Settings:
    return s if s is not None else get_settings()


def recipients(s: Settings | None = None) -> list[str]:
    return [a.strip() for a in _settings(s).digest_email_to.split(",") if a.strip()]


def email_configured(s: Settings | None = None) -> bool:
    s = _settings(s)
    return bool(s.smtp_host and recipients(s) and (s.smtp_from or s.smtp_user))


def teams_configured(s: Settings | None = None) -> bool:
    return _settings(s).teams_webhook_url.strip().lower().startswith("https://")


def parse_send_at(value: str) -> tuple[int, int] | None:
    """ "HH:MM" -> (hour, minute); None when empty or not a valid time."""
    try:
        hh, mm = value.strip().split(":")
        h, m = int(hh), int(mm)
    except ValueError:
        return None
    return (h, m) if 0 <= h < 24 and 0 <= m < 60 else None


def status(s: Settings | None = None) -> dict[str, Any]:
    """What is set up, without any secret: shown on the digest card."""
    s = _settings(s)
    at = parse_send_at(s.digest_send_at)
    on = [c for c, ok in (("email", email_configured(s)), ("teams", teams_configured(s))) if ok]
    return {
        "email": {"configured": email_configured(s), "recipients": len(recipients(s))},
        "teams": {"configured": teams_configured(s)},
        "schedule": (
            {
                "send_at": f"{at[0]:02d}:{at[1]:02d}",
                "utc_offset_minutes": s.digest_utc_offset_minutes,
                "skip_empty": s.digest_skip_empty,
            }
            if at and on
            else None
        ),
    }


# --------------------------------------------------------------------------- message bodies


def _day(d: dict[str, Any]) -> str:
    day = date.fromisoformat(d["day"])
    return f"{day.day} {day:%b %Y}"


def subject(d: dict[str, Any]) -> str:
    n = len(d["rules"]) + len(d["withdrawn"])
    if not n:
        return f"Knowledge base digest, {_day(d)}: no rule changes"
    return f"Knowledge base digest, {_day(d)}: {n} rule change{'s' if n != 1 else ''}"


def _rule_line(i: dict[str, Any]) -> tuple[str, str, str]:
    """(heading, old -> new, details) for one rule change."""
    head = f"{i['topic']}" if i["topic"] else i["summary"]
    if i["old_value"] and i["new_value"]:
        vals = f"{i['old_value']} → {i['new_value']}"
    else:
        vals = i["new_value"] or ("" if not i["topic"] else i["summary"])
    tail = []
    if i.get("effective_at"):
        tail.append(f"from {str(i['effective_at'])[:10]}")
    if i.get("source_label"):
        tail.append(i["source_label"])
    if i["status"] == "provisional":
        tail.append("provisional, awaiting the owner")
    return head, vals, " · ".join(tail)


def _footer(d: dict[str, Any]) -> list[str]:
    out = []
    if d["updates"]:
        out.append(f"{d['updates']} other knowledge updates (documents read, re-checks).")
    if d["document_edits"]:
        out.append(f"{len(d['document_edits'])} change(s) need an edit to a document in force.")
    if d["waiting_review"]:
        out.append(f"{d['waiting_review']} item(s) wait in the owner's review queue.")
    return out


def _nothing(d: dict[str, Any]) -> str:
    return "No changes to the knowledge base." if d["empty"] else "No rule changes."


def digest_html(d: dict[str, Any], link: str = "") -> str:
    e = html.escape
    rows = []
    for i in d["rules"][:MAX_ITEMS]:
        head, vals, tail = _rule_line(i)
        rows.append(
            f'<li style="margin:0 0 12px"><strong>{e(head)}</strong>'
            + (f"<br>{e(vals)}" if vals else "")
            + (f'<br><span style="color:#6b6b6b;font-size:12px">{e(tail)}</span>' if tail else "")
            + "</li>"
        )
    more = len(d["rules"]) - MAX_ITEMS
    if more > 0:
        rows.append(f"<li>and {more} more change(s)</li>")
    for i in d["withdrawn"]:
        label = "Withdrawn" if i["status"] == "rejected" else "No longer in force"
        rows.append(
            f"<li>{e(label)}: {e(i['topic'] or '')} {e(i['old_value'] or i['summary'])}</li>"
        )
    body = (
        f'<ul style="padding-left:18px">{"".join(rows)}</ul>' if rows else f"<p>{_nothing(d)}</p>"
    )
    foot = "".join(f'<p style="color:#6b6b6b;font-size:13px">{e(x)}</p>' for x in _footer(d))
    cta = f'<p><a href="{e(link, quote=True)}">Open the Changes page</a></p>' if link else ""
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1a1a1a">'
        f'<h2 style="font-size:18px;margin:0 0 12px">Changes on {e(_day(d))}</h2>'
        f"{body}{foot}{cta}</div>"
    )


def teams_message(d: dict[str, Any], link: str = "") -> dict[str, Any]:
    """The digest as an Adaptive Card message for a Teams workflow webhook."""
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": f"Changes on {_day(d)}", "weight": "Bolder", "size": "Medium"}
    ]
    for i in d["rules"][:MAX_ITEMS]:
        head, vals, tail = _rule_line(i)
        items = [{"type": "TextBlock", "text": head, "weight": "Bolder", "wrap": True}]
        if vals:
            items.append({"type": "TextBlock", "text": vals, "wrap": True, "spacing": "None"})
        if tail:
            items.append(
                {
                    "type": "TextBlock",
                    "text": tail,
                    "isSubtle": True,
                    "size": "Small",
                    "wrap": True,
                    "spacing": "None",
                }
            )
        body.append({"type": "Container", "items": items, "spacing": "Medium"})
    more = len(d["rules"]) - MAX_ITEMS
    extra = [f"and {more} more change(s)"] if more > 0 else []
    for i in d["withdrawn"]:
        label = "Withdrawn" if i["status"] == "rejected" else "No longer in force"
        extra.append(f"{label}: {i['topic'] or ''} {i['old_value'] or i['summary']}")
    if d["empty"]:
        extra.append("No changes to the knowledge base.")
    for x in extra + _footer(d):
        body.append({"type": "TextBlock", "text": x, "wrap": True, "isSubtle": True})
    card: dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }
    if link:
        card["actions"] = [
            {"type": "Action.OpenUrl", "title": "Open the Changes page", "url": link}
        ]
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


def changes_link(s: Settings | None = None) -> str:
    base = _settings(s).web_base_url.strip().rstrip("/")
    return f"{base}/changes" if base else ""


# --------------------------------------------------------------------------- transports


def _smtp(s: Settings) -> Any:  # pragma: no cover - real network
    if s.smtp_security == "ssl":
        return smtplib.SMTP_SSL(
            s.smtp_host, s.smtp_port, timeout=TIMEOUT_S, context=ssl.create_default_context()
        )
    conn = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=TIMEOUT_S)
    if s.smtp_security == "starttls":
        conn.starttls(context=ssl.create_default_context())
    return conn


def _post(url: str, data: bytes) -> int:  # pragma: no cover - real network
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return int(resp.status)


def send_email(
    d: dict[str, Any], s: Settings | None = None, smtp_factory: SmtpFactory | None = None
) -> str:
    s = _settings(s)
    to = recipients(s)
    link = changes_link(s)
    msg = EmailMessage()
    msg["Subject"] = subject(d)
    msg["From"] = s.smtp_from or s.smtp_user
    msg["To"] = ", ".join(to)
    msg.set_content(d["text"] + (f"\n\nOpen the Changes page: {link}" if link else ""))
    msg.add_alternative(digest_html(d, link), subtype="html")
    conn = (smtp_factory or _smtp)(s)
    try:
        if s.smtp_user and s.smtp_password:
            conn.login(s.smtp_user, s.smtp_password)
        conn.send_message(msg)
    finally:
        conn.quit()
    return f"sent to {len(to)} recipient{'s' if len(to) != 1 else ''}"


def send_teams(d: dict[str, Any], s: Settings | None = None, post: Post | None = None) -> str:
    s = _settings(s)
    data = json.dumps(teams_message(d, changes_link(s))).encode("utf-8")
    code = (post or _post)(s.teams_webhook_url.strip(), data)
    if not 200 <= code < 300:
        raise RuntimeError(f"Teams answered {code}")
    return "posted to the Teams channel"


def _redact(text: str, s: Settings) -> str:
    for secret in (s.teams_webhook_url.strip(), s.smtp_password):
        if secret:
            text = text.replace(secret, "[hidden]")
    return text[:300]


def deliver(
    d: dict[str, Any],
    channels: list[str] | None = None,
    s: Settings | None = None,
    smtp_factory: SmtpFactory | None = None,
    post: Post | None = None,
) -> list[dict[str, Any]]:
    """Send the digest on each channel (default: every configured one). One result per channel;
    a failing channel never stops the others."""
    s = _settings(s)
    ready = {"email": email_configured(s), "teams": teams_configured(s)}
    out = []
    for ch in channels or [c for c in CHANNELS if ready[c]]:
        if ch not in ready:
            out.append({"channel": ch, "ok": False, "detail": "unknown channel"})
            continue
        if not ready[ch]:
            out.append({"channel": ch, "ok": False, "detail": "not set up"})
            continue
        try:
            detail = send_email(d, s, smtp_factory) if ch == "email" else send_teams(d, s, post)
            out.append({"channel": ch, "ok": True, "detail": detail})
        except (OSError, smtplib.SMTPException, urllib.error.URLError, RuntimeError) as exc:
            msg = _redact(f"{type(exc).__name__}: {exc}", s)
            out.append({"channel": ch, "ok": False, "detail": msg})
    return out
