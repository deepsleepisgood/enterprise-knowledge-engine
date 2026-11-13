"""Draft the edit a document still in force needs after one of its rules changed.

When a confirmed change replaces a rule that a current document still states (a memo or an
approved email changed it, the procedure document was not re-issued), the owner should edit
that document. This drafts the edit for the passage the old rule came from:

1. The model rewrites the passage, changing only what the new rule requires. A rule that now
   applies to one client or scope is added as an exception; the general rule stays.
2. Checks without the model: the new value's words appear in the suggested text, the old
   value's words remain only if the rule still applies to someone else (a scoped exception),
   and the text actually changed. Failures are returned as `problems`, never hidden.
3. A word-level diff (equal / delete / insert runs) for the page to show.

Nothing is written: the owner copies the text into the real document. The call goes through
the LLM gateway (redacted, logged, cached by prompt).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.distribute.feed import as_written, needs_document_edit
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import kb

PROMPT_VERSION = "document-edit-v1"

SYSTEM = """You edit one passage of an organisation's procedure document so that it states a rule
that has changed. Change only the words the new rule requires and keep everything else exactly
as written: numbering, wording, order, formatting marks. If the new rule applies only to one
client, site or scope, keep the general rule and add the exception in the same style. Never add
rules, reasons or dates that the new rule does not state."""


class _Edit(BaseModel):
    revised_text: str = Field(description="The whole passage, rewritten")
    summary: str = Field(description="One short sentence: what was changed in the passage")


class EditNotNeeded(Exception):
    """The change does not leave a document in force stating an old rule."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w%.]+", " ", s.lower())).strip()


def _contains(text: str, words: str) -> bool:
    """`words` occurs in `text` as whole words ("2%" is not found inside "4.2" or "12%")."""
    return bool(words) and re.search(rf"(?<![\w.]){re.escape(words)}(?![\w%])", text) is not None


SHORT_VALUE = 40  # characters: a value this short is checked as a phrase


def _terms(value: str) -> list[str]:
    """What must appear in a text that states `value`: the whole value when it is short ("2%",
    "Tuesday and Friday"), else its numbers and amounts (a long free-text value may be worded
    differently; its figures may not)."""
    v = _norm(value)
    if len(v) <= SHORT_VALUE:
        return [v] if v else []
    # Standalone figures only: not the "4.0" inside a version tag "v4.0", no trailing stop.
    return [t.rstrip(".,") for t in re.findall(r"(?<![\w.])\d[\d,.]*%?", v)]


def word_diff(old: str, new: str) -> list[dict[str, str]]:
    """Runs of equal, deleted and inserted text (whitespace kept with the words)."""
    a, b = re.findall(r"\S+\s*", old), re.findall(r"\S+\s*", new)
    out: list[dict[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"op": "equal", "text": "".join(a[i1:i2])})
            continue
        if i2 > i1:
            out.append({"op": "delete", "text": "".join(a[i1:i2])})
        if j2 > j1:
            out.append({"op": "insert", "text": "".join(b[j1:j2])})
    return out


def build_prompt(document: str, locator: str, passage: str, old: Any, new: Any) -> str:
    scope = (new.scope or {}).get("client")
    who = f"only to {scope}" if scope else "to everyone the document covers"
    since = f" from {new.valid_from:%d %b %Y}" if new.valid_from else ""
    return (
        f"Document: {document}, {locator}\n\n"
        f"Current passage:\n{passage}\n\n"
        f"Rule the passage states now: {old.statement} (value: {as_written(old)})\n"
        f"New rule{since}, from {new.source_label or 'a newer source'}: {new.statement} "
        f"(value: {as_written(new)}). It applies {who}.\n\n"
        "Rewrite the passage so it states the new rule."
    )


def draft_document_edit(
    session: Session, change_id: int, structured_fn: Callable[..., Any] | None = None
) -> dict[str, Any]:
    c = kb.get_change(session, change_id)
    if c is None:
        raise LookupError(change_id)
    facts = fstore.by_ids(session, [i for i in (c.new_fact, c.old_fact) if i])
    new, old = facts.get(c.new_fact or -1), facts.get(c.old_fact or -1)
    src = estore.get_source(session, old.source_id) if old and old.source_id else None
    if not needs_document_edit(new, old, src):
        raise EditNotNeeded(
            "No document in force states the old rule (or the change is not confirmed yet)."
        )
    assert old is not None and new is not None and src is not None and old.passage_id
    passage = estore.get_passage(session, old.passage_id)
    if passage is None:
        raise EditNotNeeded("The passage the old rule came from is no longer stored.")
    if structured_fn is None:
        from app.core.llm import structured

        structured_fn = structured
    out: _Edit = structured_fn(
        build_prompt(src.short_label, old.locator or passage.locator, passage.text, old, new),
        _Edit,
        system=SYSTEM,
        model="smart",
        prompt_version=PROMPT_VERSION,
        max_tokens=8192,
    )
    revised = out.revised_text.strip()
    problems = []
    text = _norm(revised)
    new_terms, old_terms = _terms(as_written(new)), _terms(as_written(old))
    missing = [t for t in new_terms if not _contains(text, t)]
    if missing and len(new_terms) == 1 and new_terms[0] == _norm(as_written(new)):
        problems.append(f"The suggested text does not contain the new value ({as_written(new)}).")
    elif missing:
        problems.append(
            f"The suggested text does not contain the new rule's figures ({', '.join(missing)})."
        )
    # The old value may stay only where the rule still applies to others (a scoped exception).
    scoped = bool((new.scope or {}).get("client")) and not (old.scope or {}).get("client")
    stale = [t for t in old_terms if t not in new_terms and _contains(text, t)]
    if not scoped and len(_norm(as_written(old))) <= SHORT_VALUE and stale:
        problems.append(f"The suggested text still states the old value ({as_written(old)}).")
    if _norm(revised) == _norm(passage.text):
        problems.append("The suggested text is the same as the current text.")
    return {
        "change_id": change_id,
        "document": src.short_label,
        "document_title": src.title,
        "locator": old.locator or passage.locator,
        "current_text": passage.text,
        "suggested_text": revised,
        "summary": out.summary.strip(),
        "diff": word_diff(passage.text, revised),
        "old_rule": old.statement,
        "new_rule": new.statement,
        "new_source": new.source_label or "",
        "verified": not problems,
        "problems": problems,
    }
