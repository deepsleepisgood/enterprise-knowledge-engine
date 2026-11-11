"""Tier-1 parsers for text formats: html, markdown, plain text, eml, vtt/srt, json."""

from __future__ import annotations

import email
import json
import re
from email import policy
from typing import Any

from app.ingest.blocks import Block, clean

# ---------------------------------------------------------------- html


def parse_html(data: bytes | str) -> tuple[list[Block], dict[str, Any]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "form"]):
        tag.decompose()
    for tag in soup.select('[role="navigation"], [role="banner"], [role="contentinfo"]'):
        tag.decompose()
    title = clean(soup.title.get_text()) if soup.title else None
    blocks: list[Block] = []
    root = soup.body or soup
    for el in root.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "blockquote", "pre", "dt", "dd"]
    ):
        if el.name != "table" and el.find_parent("table"):
            continue
        if el.name in ("p", "li") and el.find_parent(["li", "blockquote"]) and el.name == "p":
            continue
        if el.name == "table":
            rows = [
                [clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
                for tr in el.find_all("tr")
            ]
            rows = [r for r in rows if any(r)]
            if rows:
                blocks.append(Block("table", rows=rows, style="table"))
            continue
        text = clean(el.get_text(" "))
        if not text:
            continue
        if el.name[0] == "h":
            blocks.append(Block("heading", text, level=int(el.name[1]), style=el.name))
        elif el.name == "li":
            depth = len(el.find_parents(["ul", "ol"])) - 1
            parent = el.find_parent(["ul", "ol"])
            ordered = parent is not None and parent.name == "ol"
            blocks.append(
                Block("list_item", text, level=max(depth, 0), style="li", meta={"ordered": ordered})
            )
        elif el.name == "blockquote":
            blocks.append(Block("quote", text, style="blockquote"))
        else:
            blocks.append(Block("paragraph", text, style=el.name))
    if not blocks:  # bare text in divs
        for chunk in re.split(r"\n\s*\n", root.get_text("\n")):
            if clean(chunk):
                blocks.append(Block("paragraph", clean(chunk)))
    return blocks, {"title": title} if title else {}


# ---------------------------------------------------------------- markdown and plain text

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_LIST = re.compile(r"^(\s*)([-*+•]|\d{1,3}[.)])\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> list[str]:
    return [clean(c) for c in line.strip().strip("|").split("|")]


def parse_text(data: bytes | str, markdown: bool = True) -> tuple[list[Block], dict[str, Any]]:
    text = data.decode("utf-8-sig", errors="replace") if isinstance(data, bytes) else data
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append(Block("paragraph", clean(" ".join(para))))
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            flush()
        elif markdown and (m := _MD_HEADING.match(s)):
            flush()
            blocks.append(Block("heading", clean(m.group(2)), level=len(m.group(1)), style="md"))
        elif (
            # A pipe table with its |---| line is a table in any plain text (an email body).
            s.startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1].strip())
        ):
            flush()
            rows = [_split_row(s)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            blocks.append(Block("table", rows=rows))
            continue
        elif (
            not markdown
            and (m := _MD_LIST.match(line))
            and m.group(2)[0].isdigit()
            and len(s) < 80
            and not s.endswith((".", ",", ";", ":"))
            and (i == 0 or not lines[i - 1].strip())
            and (i + 1 >= len(lines) or not lines[i + 1].strip())
        ):
            # A short numbered line standing alone in plain text ("7. Approvals") is a section
            # title, not a one-item list: keep its number so heading inference can use it.
            flush()
            blocks.append(Block("paragraph", clean(s)))
        elif (m := _MD_LIST.match(line)) and not re.match(r"^\d{1,2}:\d{2}", s):
            flush()
            blocks.append(
                Block(
                    "list_item",
                    clean(m.group(3)),
                    level=len(m.group(1)) // 2,
                    meta={"ordered": m.group(2)[0].isdigit()},
                )
            )
        elif markdown and s.startswith(">"):
            flush()
            blocks.append(Block("quote", clean(s.lstrip("> "))))
        elif re.match(r"^\[?\d{1,2}:\d{2}", s):  # a timestamped line stands alone
            flush()
            blocks.append(Block("paragraph", clean(s)))
        else:
            para.append(s)
        i += 1
    flush()
    return blocks, {}


# ---------------------------------------------------------------- email

_QUOTE_HEADER = re.compile(
    r"^(On .{5,200}wrote:|-{2,}\s*Original Message\s*-{2,}|From: .+\nSent: |_{10,})", re.M | re.I
)
_SIGNOFF = re.compile(
    r"^(--\s*$|regards,?$|best regards,?$|kind regards,?$|thanks,?$|thank you,?$|cheers,?$|"
    r"sent from my )",
    re.I,
)


def strip_reply_and_signature(body: str) -> tuple[str, dict[str, Any]]:
    """Remove quoted earlier messages and the signature block. Returns (text, what was cut)."""
    cut: dict[str, Any] = {}
    m = _QUOTE_HEADER.search(body)
    if m:
        cut["quoted_chars"] = len(body) - m.start()
        body = body[: m.start()]
    kept = [ln for ln in body.split("\n") if not ln.lstrip().startswith(">")]
    if len(kept) != len(body.split("\n")):
        cut["quoted_lines"] = len(body.split("\n")) - len(kept)
    lines = kept
    for i in range(len(lines) - 1, -1, -1):
        if _SIGNOFF.match(lines[i].strip()) and len(lines) - i <= 8:
            cut["signature_lines"] = len(lines) - i
            lines = lines[:i]
            break
    return "\n".join(lines).strip(), cut


def parse_eml(data: bytes) -> tuple[list[Block], dict[str, Any]]:
    msg = email.message_from_bytes(data, policy=policy.default)
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        body = body_part.get_content()
        if body_part.get_content_type() == "text/html":
            from bs4 import BeautifulSoup

            body = BeautifulSoup(body, "html.parser").get_text("\n")
    body, cut = strip_reply_and_signature(body)
    blocks, _ = parse_text(body, markdown=False)
    subject = str(msg.get("Subject", "") or "")
    if subject:
        blocks.insert(0, Block("heading", clean(subject), level=1, style="subject"))
    meta = {
        "from": str(msg.get("From", "") or ""),
        "to": str(msg.get("To", "") or ""),
        "date": str(msg.get("Date", "") or ""),
        "subject": subject,
        "message_id": str(msg.get("Message-ID", "") or ""),
        "attachments": [p.get_filename() for p in msg.iter_attachments() if p.get_filename()],
        **cut,
    }
    return blocks, {k: v for k, v in meta.items() if v}


def email_attachments(data: bytes) -> list[tuple[str, bytes]]:
    msg = email.message_from_bytes(data, policy=policy.default)
    out = []
    for part in msg.iter_attachments():
        name = part.get_filename()
        payload = part.get_payload(decode=True)
        if name and payload:
            out.append((name, payload))
    return out


# ---------------------------------------------------------------- vtt / srt

_CUE_TIME = re.compile(r"(\d{1,2}:)?(\d{2}):(\d{2})[.,]\d{3}\s*-->")


def parse_cues(data: bytes) -> tuple[list[Block], dict[str, Any]]:
    text = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    blocks: list[Block] = []
    for cue in re.split(r"\n\s*\n", text):
        lines = [ln for ln in cue.strip().split("\n") if ln.strip()]
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue
        m = _CUE_TIME.search(lines[idx])
        if not m:
            continue
        hours = (m.group(1) or "").rstrip(":")
        stamp = (
            f"{int(hours):02d}:{m.group(2)}:{m.group(3)}"
            if hours and int(hours)
            else f"{m.group(2)}:{m.group(3)}"
        )
        body = clean(" ".join(lines[idx + 1 :]))
        speaker = None
        sv = re.match(r"^<v\s+([^>]+)>(.*)$", body)
        if sv:
            speaker, body = sv.group(1).strip(), re.sub(r"</v>", "", sv.group(2)).strip()
        else:
            sp = re.match(r"^([A-Z][\w .'\-]{0,40}):\s+(.*)$", body)
            if sp:
                speaker, body = sp.group(1), sp.group(2)
        body = re.sub(r"<[^>]+>", "", body)
        if body:
            blocks.append(
                Block(
                    "turn",
                    body,
                    time=stamp,
                    time_style="bracket",
                    speaker=speaker,
                    position={"time_range": lines[idx].strip()},
                )
            )
    # Merge consecutive cues from the same speaker into one turn.
    merged: list[Block] = []
    for b in blocks:
        if merged and b.speaker and merged[-1].speaker == b.speaker:
            merged[-1].text = clean(merged[-1].text + " " + b.text)
        else:
            merged.append(b)
    return merged, {}


# ---------------------------------------------------------------- json (chat exports)


def parse_json(data: bytes) -> tuple[list[Block], dict[str, Any]]:
    obj = json.loads(data.decode("utf-8-sig"))
    items = obj.get("messages") if isinstance(obj, dict) else obj
    blocks: list[Block] = []
    if isinstance(items, list) and items and all(isinstance(m, dict) for m in items):
        for m in items:
            body = m.get("body") or m.get("text") or m.get("content") or m.get("message") or ""
            if isinstance(body, dict):
                body = body.get("content", "")
            body = re.sub(r"<[^>]+>", " ", str(body))
            sender = m.get("from") or m.get("sender") or m.get("author") or m.get("user")
            if isinstance(sender, dict):
                sender = (
                    sender.get("name")
                    or sender.get("displayName")
                    or sender.get("user", {}).get("displayName")
                )
            when = m.get("createdDateTime") or m.get("timestamp") or m.get("date") or m.get("ts")
            if clean(body):
                blocks.append(
                    Block(
                        "turn",
                        clean(body),
                        speaker=str(sender) if sender else None,
                        time=None,
                        position={"sent_at": str(when) if when else None},
                        meta={"message": True},
                    )
                )
        return blocks, {"messages": len(blocks)}

    def walk(o: Any, path: str) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
        elif o is not None and str(o).strip():
            blocks.append(Block("paragraph", f"{path}: {o}"))

    walk(obj, "")
    return blocks, {}
