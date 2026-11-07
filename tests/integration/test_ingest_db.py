"""Phase 1 acceptance against the database: the Meridian corpus through the generic pipeline.

No hand-written pack and no LLM here (the metadata classifier is switched off so the test is
deterministic); `test_metadata_baseline.py` covers the classifier against the hand-copied index.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import date
from pathlib import Path

import docx
import pytest

from app import worker
from app.core.config import get_settings
from app.core.db import session_scope
from app.ingest import pipeline
from app.ingest.connectors import from_eml, from_paths, from_text, from_upload
from app.ingest.intake import submit
from app.store import episodes as store

pytestmark = pytest.mark.db
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"


@pytest.fixture
def no_llm(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "_llm_structured", lambda: None)
    monkeypatch.setattr(get_settings(), "blob_dir", tmp_path / "blobs")


def _ingest(paths) -> tuple[int, float]:
    started = time.perf_counter()
    with session_scope() as s:
        created = sum(submit(s, ep)[1] for ep in from_paths(paths))
    worker.drain(kinds=["parse_episode"], threads=2)
    return created, time.perf_counter() - started


def _by_label(s) -> dict[str, tuple]:
    out = {}
    for src in store.list_sources(s):
        out[src.part_label or src.short_label] = (src, store.passages_for_source(s, src.id))
    return out


def test_corpus_ingests_with_expected_structure(db, no_llm) -> None:
    created, seconds = _ingest([RAW])
    assert created == 4
    assert seconds < 120, f"parsing took {seconds:.0f}s"
    with session_scope() as s:
        assert store.episode_counts(s) == {"parsed": 4}
        docs = _by_label(s)
        assert len(docs) == 14
        sop4 = next(v for k, v in docs.items() if k.endswith("v4.0"))
        top = {p.locator for p in sop4[1] if re.fullmatch(r"\d+", p.locator)}
        assert top == {str(i) for i in range(1, 15)}
        assert sum(1 for p in sop4[1] if re.fullmatch(r"\d+\.\d+", p.locator)) >= 17
        faq = docs["Part F"][1]
        assert sum(1 for p in faq if p.segment_kind == "table_row") == 10
        assert sum(1 for p in docs["Video 1"][1] if p.segment_kind == "turn") == 9
        assert sum(1 for p in docs["Shadowing notes"][1] if p.segment_kind == "note") == 9
        for label, (src, ps) in docs.items():
            assert src.dated is not None, label
            assert src.status and src.short_label and src.doc_type, label
            for p in ps:
                assert p.locator and p.context_header and p.text, (label, p.id)
                assert p.source_id == src.id and p.episode_id == src.episode_id
                assert f"status {src.status}" in p.context_header


def test_interview_turns_match_the_transcript(db, no_llm) -> None:
    _ingest([RAW / "PS-07_training_and_expert_transcripts.docx"])
    d = docx.Document(str(RAW / "PS-07_training_and_expert_transcripts.docx"))
    answers: Counter[str] = Counter()
    section = None
    for p in d.paragraphs:
        if p.style.name.startswith("Heading"):
            section = p.text.split(" — ")[0]
        m = re.match(r"^\[\d{2}:\d{2}\] ([^:]+):", p.text)
        if m and m.group(1) != "Interviewer" and section:
            answers[section] += 1
    with session_scope() as s:
        docs = _by_label(s)
        for name in ("Expert interview 1", "Expert interview 2"):
            turns = [p for p in docs[name][1] if p.segment_kind == "turn"]
            assert len(turns) == answers[name], name
            # Timestamps exactly as written.
            assert all(re.search(r"\[\d{2}:\d{2}\]$", p.locator) for p in turns)


def test_reingest_is_idempotent(db, no_llm) -> None:
    _ingest([RAW])
    with session_scope() as s:
        before = (len(store.list_sources(s)), len(store.all_passages(s)))
    created, _ = _ingest([RAW])
    assert created == 0
    with session_scope() as s:
        assert (len(store.list_sources(s)), len(store.all_passages(s))) == before
        assert all(e.confirmations == 1 for e in store.list_episodes(s))


def test_new_version_supersedes_old_in_either_order(db, no_llm) -> None:
    _ingest([RAW / "PS-07_AP_SOP_v4.0_2026.docx"])
    _ingest([RAW / "PS-07_AP_SOP_v3.1_2023.docx"])  # the older one arrives later
    with session_scope() as s:
        srcs = {s_.version: s_ for s_ in store.list_sources(s)}
        old, new = srcs["3.1"], srcs["4.0"]
        assert old.status == "superseded" and old.valid_until == date(2026, 3, 31)
        assert new.status == "current" and new.supersedes_source_id == old.id
        assert all(
            "status superseded" in p.context_header for p in store.passages_for_source(s, old.id)
        )


def test_planted_identifiers_are_redacted_at_ingest(db, no_llm) -> None:
    text = "Supplier tax id ABCDE1234F, a/c no 123456789012, call 9876543210 to confirm."
    with session_scope() as s:
        eid, _ = submit(s, from_text(text, subject="Bank details", sender="x@example.com"))
    worker.drain(kinds=["parse_episode"])
    with session_scope() as s:
        body = " ".join(p.text for p in store.passages_for_episode(s, eid))
        assert "ABCDE1234F" not in body and "123456789012" not in body
        assert "9876543210" not in body and "[REDACTED_PAN]" in body


def test_email_with_attachment_and_unknown_file(db, no_llm) -> None:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "Controller <fc@example.com>"
    msg["To"] = "team@example.com"
    msg["Subject"] = "Bulk tolerance"
    msg["Date"] = "Mon, 9 Nov 2026 10:00:00 +0530"
    msg.set_content("From Monday 16 Nov the bulk tolerance is 7%.\n\nRegards,\nPriya")
    msg.add_attachment(
        b"# Note\n\nSee the memo.", maintype="text", subtype="markdown", filename="note.md"
    )
    eps = from_eml(msg.as_bytes())
    assert len(eps) == 2 and eps[0].sender == "fc@example.com"
    assert eps[0].received_at.date() == date(2026, 11, 9)
    eps += from_upload("mystery.bin", b"\x00\x01\x02\x03" * 64)
    with session_scope() as s:
        ids = [submit(s, e)[0] for e in eps]
    worker.drain(kinds=["parse_episode"])
    with session_scope() as s:
        mail, attach, mystery = (store.get_episode(s, i) for i in ids)
        assert mail.status == "parsed" and attach.status == "parsed"
        (src,) = store.list_sources(s, mail.id)
        assert src.doc_type == "email" and src.dated == date(2026, 11, 9)
        assert "Priya" not in " ".join(p.text for p in store.passages_for_episode(s, mail.id))
        assert mystery.status == "needs_attention" and mystery.error
