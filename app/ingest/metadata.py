"""Document metadata inference with provenance (SCOPE.md 3.5, layer 3).

Order of evidence: the document's header table, its title and headings, file properties and the
file name, then a MODEL_FAST classifier for what text patterns cannot settle (document type,
short label, client scope, owner, status). Each field records its origin and a confidence.
Date precedence: explicit effective date in the text > document date in the header > email sent
date > file modified time > ingestion time.
"""

from __future__ import annotations

import contextlib
import itertools
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.ingest.segment import DocPart, norm_key

PROMPT_VERSION = "docmeta-v1"
LOW_CONFIDENCE = 0.7

DOC_TYPES = [
    "policy",
    "sop",
    "work_instruction",
    "memo",
    "faq",
    "training",
    "interview",
    "observation",
    "email",
    "chat",
    "spreadsheet",
    "slides",
    "report",
    "contract",
    "form",
    "expert_answer",
    "other",
]
STATUSES = ["current", "superseded", "draft", "stale", "record"]

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        1,
    )
}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MON = (
    r"(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
)
_DATE_PATTERNS = [
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON}\.?,?\s+(\d{{4}})\b", re.I), "dmy"),
    (re.compile(rf"\b{_MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I), "mdy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    (re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b"), "dmy_num"),
    (re.compile(rf"\b{_MON}\.?\s+(\d{{4}})\b", re.I), "my"),
]
_VERSION = re.compile(r"\b(?:version|ver\.?|rev(?:ision)?\.?|v)\s*(\d+(?:\.\d+){0,3})\b", re.I)
_REF = re.compile(r"\b([A-Z]{1,6}(?:-[A-Z0-9]{1,8}){1,3})\b")
_STATUS_WORDS = [
    (re.compile(r"\b(superseded|replaced by|withdrawn|obsolete|archived)\b", re.I), "superseded"),
    (re.compile(r"\bdraft\b", re.I), "draft"),
    (re.compile(r"\b(not reviewed since|outdated|out of date|deprecated)\b", re.I), "stale"),
]

KEY_CLASSES: dict[str, list[str]] = {
    "title": ["document", "title", "subject", "name"],
    "version": ["version", "rev", "revision", "edition"],
    "ref": ["reference", "ref", "document id", "doc id", "id"],
    "effective": ["effective", "effective from", "effective date"],
    "doc_date": [
        "dated",
        "date",
        "issued",
        "issue date",
        "updated",
        "last updated",
        "recorded",
        "published",
        "approved",
        "last reviewed",
        "reviewed",
    ],
    "valid_until": ["valid until", "valid till", "expires", "expiry", "review date"],
    "owner": [
        "owner",
        "issued by",
        "from",
        "author",
        "prepared by",
        "presenter",
        "interviewer",
        "observer",
    ],
    "status": ["status"],
    "supersedes": ["replaces", "supersedes"],
    "scope": ["applies to", "scope", "audience", "client", "department"],
}


def parse_date(text: str) -> tuple[date, str] | None:
    """First date in `text` and its precision ("day" or "month")."""
    best: tuple[int, date, str] | None = None
    for rx, kind in _DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                if kind == "dmy":
                    d = date(int(m.group(3)), _MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
                    prec = "day"
                elif kind == "mdy":
                    d = date(int(m.group(3)), _MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
                    prec = "day"
                elif kind == "iso":
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    prec = "day"
                elif kind == "dmy_num":
                    d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                    prec = "day"
                else:
                    d = date(int(m.group(2)), _MONTHS[m.group(1).lower()[:3]], 1)
                    prec = "month"
            except (ValueError, KeyError):
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), d, prec)
    return (best[1], best[2]) if best else None


@dataclass
class Field_:
    value: Any
    origin: str
    confidence: float


@dataclass
class DocMeta:
    fields: dict[str, Field_] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        f = self.fields.get(name)
        return f.value if f is not None and f.value not in (None, "") else default

    def put(self, name: str, value: Any, origin: str, confidence: float) -> None:
        if value in (None, ""):
            return
        cur = self.fields.get(name)
        if cur is None or confidence > cur.confidence:
            self.fields[name] = Field_(value, origin, confidence)

    def provenance(self) -> dict[str, Any]:
        return {k: {"origin": f.origin, "confidence": f.confidence} for k, f in self.fields.items()}

    def low_confidence(self) -> list[str]:
        return [k for k, f in self.fields.items() if f.confidence < LOW_CONFIDENCE]


class _LLMDocMeta(BaseModel):
    doc_type: Literal[tuple(DOC_TYPES)] = Field(description="Kind of document")  # type: ignore[valid-type]
    short_label: str = Field(
        description="How staff would cite it, at most 20 characters: an "
        "abbreviation of its title plus version, e.g. 'Handbook "
        "v2.1'. Never a file-name prefix or project code"
    )
    title: str = Field(description="A clean document title")
    client_scope: str = Field(
        description="The one external client or customer this document's "
        "rules are restricted to. 'all' if it applies "
        "generally, names several clients, or is about the "
        "organisation's own teams, roles or people"
    )
    owner: str | None = Field(None, description="Team, role or person responsible for it")
    status: Literal[tuple(STATUSES)] = Field(  # type: ignore[valid-type]
        description="current; superseded (says it is replaced); draft; stale (an export or "
        "page that says it was last updated or reviewed more than two years before "
        "today); record (an interview, observation or meeting record)"
    )
    status_reason: str = ""
    practice: bool = Field(
        description="True if it records personal practice, opinions or "
        "observations rather than official rules or training"
    )
    confidence: float = Field(ge=0, le=1, description="Your confidence in doc_type and scope")


SYSTEM = """You classify one document from an organisation's knowledge base using only its header.
Answer from the text given. Do not invent dates, versions or owners that are not stated."""


def _header_text(doc: DocPart, file_meta: dict[str, Any], filename: str, today: date) -> str:
    lines = [f"Today: {today.isoformat()}"]
    if doc.container_title:
        lines.append(f"File title: {doc.container_title}")
    lines.append(f"File name: {filename}")
    if doc.heading is not None:
        lines.append(f"Section heading: {doc.heading.text}")
    elif doc.title:
        lines.append(f"Title: {doc.title}")
    for k, v in doc.meta_kv.items():
        lines.append(f"{k}: {v}")
    if file_meta.get("subject") and file_meta.get("from"):
        lines.append(
            f"Email from {file_meta['from']} on {file_meta.get('date')}: {file_meta['subject']}"
        )
    body = " ".join(
        b.text or " ".join(" ".join(r) for r in b.rows[:4])
        for b in [*doc.preamble, *doc.blocks][:12]
    )
    lines.append(f"Opening text: {body[:1200]}")
    return "\n".join(lines)


def _from_table(m: DocMeta, kv: dict[str, str]) -> None:
    for key, value in kv.items():
        nk = norm_key(key)
        for cls, keys in KEY_CLASSES.items():
            if nk not in keys:
                continue
            origin = f"header table '{key}'"
            if cls in ("effective", "doc_date", "valid_until"):
                pd = parse_date(value)
                if pd:
                    conf = 0.95 if pd[1] == "day" else 0.85
                    target = {
                        "effective": "effective",
                        "doc_date": "doc_date",
                        "valid_until": "valid_until",
                    }[cls]
                    # Earlier keys in the class list are stronger (effective > updated > ...).
                    conf -= keys.index(nk) * 0.01
                    m.put(target, pd[0], origin, conf)
            elif cls == "version":
                vm = _VERSION.search(value) or re.search(r"(\d+(?:\.\d+){0,3})", value)
                if vm:
                    m.put("version", vm.group(1), origin, 0.95)
            elif cls == "ref":
                rm = _REF.search(value)
                if rm:
                    m.put("ref", rm.group(1), origin, 0.95)
                vm = _VERSION.search(value)
                if vm:
                    m.put("version", vm.group(1), origin, 0.93)
            elif cls == "owner":
                m.put("owner", value, origin, 0.92 - keys.index(nk) * 0.03)
            elif cls == "status":
                m.put("status_text", value, origin, 0.9)
            elif cls == "title":
                m.put("title", value, origin, 0.9 - keys.index(nk) * 0.02)
            else:
                m.put(cls, value, origin, 0.9)
            break


_KV_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z ]{1,28}?)\s*:\s*(\S.{0,120}?)\s*$")


def _kv_lines(texts: Any) -> dict[str, str]:
    """'Key: value' lines whose key is a known header field (Version, Effective, Owner...)."""
    known = {k for keys in KEY_CLASSES.values() for k in keys}
    out: dict[str, str] = {}
    for text in texts:
        for line in (text or "").splitlines():
            mm = _KV_LINE.match(line)
            if mm and norm_key(mm.group(1)) in known:
                out.setdefault(mm.group(1).strip(), mm.group(2))
    return out


def _from_text(m: DocMeta, text: str, origin: str, conf: float, refs: bool = False) -> None:
    vm = _VERSION.search(text)
    if vm:
        m.put("version", vm.group(1), origin, conf)
    rm = _REF.search(text) if refs else None
    if rm:
        m.put("ref", rm.group(1), origin, conf - 0.05)
    eff = re.search(
        r"\b(?:effective|in force|applies)[:\s]+(?:from\s+|on\s+)?(.{0,40})", text, re.I
    )
    if eff and (pd := parse_date(eff.group(1))):
        m.put("effective", pd[0], f"{origin} (effective)", conf)
    upd = re.search(
        r"\b(?:last updated|updated|last reviewed|reviewed|dated|issued)[:\s]+(?:on\s+)?(.{0,40})",
        text,
        re.I,
    )
    if upd and (pd := parse_date(upd.group(1))):
        m.put("doc_date", pd[0], f"{origin} (updated)", conf - 0.05)
    for rx, status in _STATUS_WORDS:
        if rx.search(text):
            m.put("status_hint", status, origin, conf - 0.1)
            break


def infer(
    doc: DocPart,
    *,
    filename: str,
    file_meta: dict[str, Any],
    received_at: datetime,
    channel: str,
    llm_fn: Any | None = None,
) -> DocMeta:
    m = DocMeta(raw={"header": doc.meta_kv, "file": file_meta})
    _from_table(m, doc.meta_kv)
    # Formats without a header table (PDF, Markdown) write it as "Key: value" lines on top.
    lead = list(
        itertools.takewhile(lambda b: b.type != "heading", [*doc.preamble, *doc.blocks][:12])
    )
    lines = _kv_lines(b.text for b in lead if b.type == "paragraph")
    if lines:
        _from_table(m, {k: v for k, v in lines.items() if k not in doc.meta_kv})
        m.raw["header"] = {**lines, **doc.meta_kv}
    heading = doc.heading.text if doc.heading is not None else (doc.title or "")
    if heading:
        _from_text(m, heading, "heading", 0.85, refs=True)
    for b in doc.preamble[:6]:
        if b.type == "paragraph":
            _from_text(m, b.text, "first-page text", 0.8)
    _from_text(m, filename, "file name", 0.6)
    if doc.label:
        m.put("part_label", doc.label, "heading", 0.95)
    is_email = channel in ("email", "expert_answer") or bool(
        file_meta.get("from") and file_meta.get("subject")
    )
    if file_meta.get("date") and is_email:
        from email.utils import parsedate_to_datetime

        with contextlib.suppress(TypeError, ValueError):
            m.put(
                "doc_date",
                parsedate_to_datetime(file_meta["date"]).date(),
                "email Date header",
                0.8,
            )
    if file_meta.get("modified"):
        with contextlib.suppress(ValueError):
            m.put(
                "doc_date",
                datetime.fromisoformat(file_meta["modified"]).date(),
                "file modified time",
                0.3,
            )
    m.put("doc_date", received_at.date(), "ingestion time", 0.1)
    title = m.get("title") or (doc.title if doc.heading is not None else None) or doc.title
    m.put("title", title or file_meta.get("title") or filename, "heading or file", 0.6)

    if llm_fn is not None:
        out: _LLMDocMeta = llm_fn(
            _header_text(doc, file_meta, filename, received_at.date()),
            _LLMDocMeta,
            system=SYSTEM,
            model="fast",
            prompt_version=PROMPT_VERSION,
            max_tokens=4096,
        )
        c = max(0.5, min(out.confidence, 0.9))
        m.put("doc_type", out.doc_type, "classifier", c)
        m.put("short_label", out.short_label[:40], "classifier", 0.7)
        m.put("client_scope", _scope(out.client_scope), "classifier", c)
        m.put("owner", out.owner, "classifier", 0.6)
        m.put("status_hint", out.status, f"classifier: {out.status_reason[:80]}", 0.75)
        m.put("practice", out.practice, "classifier", 0.75)
        m.put("title_clean", out.title, "classifier", 0.7)
    else:
        m.put("client_scope", "all", "default", 0.5)
    # The document's own words for its type ("Client memo", "FAQ") beat the classifier.
    own = _type_by_keywords(" ".join([heading, m.get("title") or ""]), channel)
    if own:
        m.put("doc_type", own, "heading words", 0.92)
    m.put("doc_type", "other", "default", 0.3)
    # Citation label: the document's own reference code, else its section label.
    if m.get("ref") and m.fields["ref"].confidence >= 0.75:
        m.put("short_label", m.get("ref"), m.fields["ref"].origin, 0.9)
    elif doc.label and not _NUMBERED_LABEL.match(doc.label):
        m.put("short_label", doc.label, "section label", 0.85)

    # Final, derived fields.
    dated = m.fields.get("effective") or m.fields.get("doc_date")
    if dated:
        m.fields["dated"] = dated
    status = m.get("status_hint") or "current"
    if m.get("status_text"):
        for rx, st in _STATUS_WORDS:
            if rx.search(m.get("status_text")):
                status = st
    m.put(
        "status",
        status,
        (m.fields.get("status_hint") or Field_(None, "default", 0.5)).origin,
        m.fields["status_hint"].confidence if "status_hint" in m.fields else 0.5,
    )
    if not m.get("short_label"):
        m.put("short_label", _fallback_label(m, doc), "derived", 0.5)
    return m


_NUMBERED_LABEL = re.compile(r"^\d")
# Generic words documents use to name their own type (any organisation).
_TYPE_WORDS = [
    (r"\b(faq|frequently asked questions)\b", "faq"),
    (r"\bmemo(randum)?\b", "memo"),
    (r"\binterview\b", "interview"),
    (r"\b(shadowing|observation notes?|field notes)\b", "observation"),
    (r"\b(desk|work|working) instructions?\b", "work_instruction"),
    (r"\b(standard operating procedure|sop)\b", "sop"),
    (r"\b(training|video|webinar|course|lesson)\b", "training"),
    (r"\bpolicy\b", "policy"),
    (r"\b(minutes|report)\b", "report"),
]


def _type_by_keywords(text: str, channel: str) -> str | None:
    if channel in ("email", "expert_answer"):
        return channel
    t = text.lower()
    for rx, kind in _TYPE_WORDS:
        if re.search(rx, t):
            return kind
    return None


def _scope(value: str | None) -> str:
    """'all' for empty answers and for lists of several organisations."""
    v = (value or "").strip()
    if not v or v.lower() in ("all", "general", "none", "n/a", "everyone"):
        return "all"
    if len(re.split(r",|;|\band\b|&", v)) >= 2:
        return "all"
    return v


def _fallback_label(m: DocMeta, doc: DocPart) -> str:
    if m.get("ref"):
        return m.get("ref")
    if doc.label:
        return doc.label
    title = m.get("title") or "Document"
    words = re.sub(r"[^\w ]+", " ", title).split()
    short = " ".join(words[:3])
    return f"{short} v{m.get('version')}" if m.get("version") else short
