"""Score a conflict scan against the known_conflicts sheet (TEST_PLAN level 6). Test code only.

A known conflict lists the current rule's file and section, the conflicting statements' files
and sections, and the authoritative source. A detected conflict matches it when its
authoritative passage is in one of the current locations and its other passage is in one of
the conflicting locations (for an internal inconsistency, both passages in the named section).
When several known conflicts share those locations, the one whose topic words overlap the
detected conflict's attribute and statements most is chosen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1] / "eval" / "PS-07_qa_evaluation_set.xlsx"
_FILE = re.compile(r"(PS-07_[\w.\-]+?\.docx)")
_LOC = re.compile(r"§\s*([\d.]+)|\b(Part [A-Z])\b|\b(Video \d+)\b|\b(Interview \d+)\b", re.I)


@dataclass
class Place:
    file: str
    section: str  # "4.2", "part c", "video 2" or "" (anywhere in the file)


@dataclass
class Known:
    id: str
    topic: str
    current: list[Place]
    conflicting: list[Place]
    authoritative: str
    internal: bool = False
    detail: str = ""  # the values both sides state (after each "file §x:"), for tie-breaks


@dataclass
class Detected:
    """One detected conflict, with both sides placed in the corpus."""

    auth_file: str
    auth_loc: str
    other_file: str
    other_loc: str
    auth_source: str
    kind: str
    text: str  # attribute, statements and values, for topic overlap
    extra: dict = field(default_factory=dict)
    auth_also: list[tuple[str, str]] = field(default_factory=list)  # same value, same source

    def auth_in(self, ps: list[Place]) -> bool:
        return any(
            in_place(f, loc, ps) for f, loc in [(self.auth_file, self.auth_loc), *self.auth_also]
        )


def places(text: str) -> list[Place]:
    """'A.docx §3 and B.docx Part F: value' -> [Place(A, '3'), Place(B, 'part f')]."""
    head = re.sub(r"\[[^\]]*\]", " ", text).split(":")[0]  # "[03:40]" is not the colon
    out = []
    parts = _FILE.split(head)
    for i in range(1, len(parts), 2):
        tail = parts[i + 1] if i + 1 < len(parts) else ""
        m = _LOC.search(tail.split(",")[0].split(" and ")[0])
        sec = next((g for g in m.groups() if g), "") if m else ""
        out.append(Place(parts[i], sec.lower()))
    return out


def load_known(path: Path = EVAL) -> list[Known]:
    from openpyxl import load_workbook

    ws = load_workbook(path, read_only=True)["known_conflicts"]
    rows = list(ws.iter_rows(values_only=True))
    head = [str(h) for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not r or not r[0]:
            continue
        d = dict(zip(head, r, strict=False))
        cur, con = (
            places(str(d["current_rule_and_source"])),
            places(str(d["conflicting_statement_and_source"])),
        )
        out.append(
            Known(
                id=str(d["conflict_id"]),
                topic=str(d["topic"]),
                current=cur,
                conflicting=con,
                authoritative=str(d["authoritative_source"]),
                internal=not con,
                detail=" ".join(
                    _after_colon(str(d[c]))
                    for c in ("current_rule_and_source", "conflicting_statement_and_source")
                ),
            )
        )
    return out


def in_place(file: str, loc: str, ps: list[Place]) -> bool:
    loc = re.sub(r"\([^)]*\)", " ", (loc or "").replace("§", " ")).lower().strip()
    for p in ps:
        if p.file != file:
            continue
        if not p.section:
            return True
        s = p.section
        if re.fullmatch(r"[\d.]+", s):
            head = re.match(r"[\d.]+", loc)
            if head and (head.group(0).rstrip(".") == s or head.group(0).startswith(s + ".")):
                return True
        elif loc.startswith(s) or f" {s}" in f" {loc}":
            return True
    return False


_STOP = {"the", "and", "of", "in", "for", "to", "a", "an", "on", "check"}


def words(s: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]{3,}", s.lower())} - _STOP


def _after_colon(text: str) -> str:
    return re.sub(r"\[[^\]]*\]", " ", text).partition(":")[2]


def tokens(s: str) -> set[str]:
    """Words and numbers ("45 days" -> {"45", "day"}), for comparing stated values."""
    nums = {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*", s)}
    return words(s) | {n for n in nums if n}


def candidates(d: Detected, key: list[Known]) -> list[Known]:
    out = []
    for k in key:
        if k.internal:
            ok = (
                d.kind == "self_contradiction"
                and d.auth_in(k.current)
                and in_place(d.other_file, d.other_loc, k.current)
            )
        else:
            ok = d.auth_in(k.current) and in_place(d.other_file, d.other_loc, k.conflicting)
        if ok:
            out.append(k)
    return out


def match(d: Detected, key: list[Known]) -> Known | None:
    cands = candidates(d, key)
    if len(cands) <= 1:
        return cands[0] if cands else None
    # Topic words first; on a tie, the values each known conflict names ("45 days ... 60 days"
    # vs "Tuesday and Friday") decide which one the detected pair is.
    dw, dt = words(d.text), tokens(d.text)
    scored = sorted(cands, key=lambda k: (-len(words(k.topic) & dw), -len(tokens(k.detail) & dt)))
    best = scored[0]
    return best if words(best.topic) & dw else None


def authoritative_ok(d: Detected, k: Known) -> bool:
    want = k.authoritative.split("§")[0].strip().lower()
    return want in d.auth_source.lower()


def score(detected: list[Detected], key: list[Known]) -> dict:
    hits: dict[str, list[Detected]] = {}
    extra = []
    for d in detected:
        k = match(d, key)
        if k is None:
            extra.append(d)
        else:
            hits.setdefault(k.id, []).append(d)
    found = sorted(hits)
    auth_right = [
        kid
        for kid in found
        if any(authoritative_ok(d, next(k for k in key if k.id == kid)) for d in hits[kid])
    ]
    return {
        "recall": len(found),
        "total": len(key),
        "found": found,
        "missed": [k.id for k in key if k.id not in hits],
        "authoritative_right": auth_right,
        "hits": hits,
        "extra": extra,
    }
