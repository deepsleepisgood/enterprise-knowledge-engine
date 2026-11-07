"""Ingestion tests (TEST_PLAN level 2) that need no database."""

from __future__ import annotations

import re
from collections import Counter

import docx
import pytest

from app.core.config import get_settings
from app.core.pack import DocumentSpec
from app.ingest.docx_parser import read_blocks
from app.ingest.passages import finalise, parse_corpus
from app.ingest.segmenters import segment_document


def _by_source(corpus, source_id):
    return [p for p in corpus.passages if p.source_id == source_id]


def _locators(corpus):
    return {(p.source_id, p.locator) for p in corpus.passages}


def test_every_passage_has_provenance(corpus, pack) -> None:
    for p in corpus.passages:
        src = pack.sources[p.source_id]
        assert src.file, p
        assert p.locator and p.text.strip(), p
        assert p.valid_from is not None, f"no date on {p.locator}"
        assert p.source_status in {
            "current",
            "superseded",
            "stale",
            "partly_outdated",
            "observation",
            "knowledge_capture",
        }
        if src.kind in ("sop", "desk_instruction", "client_memo"):
            assert src.version, f"{src.id} needs a version"
        assert p.context_header


def test_sop_v4_has_14_top_level_sections(corpus) -> None:
    tops = {p.locator for p in _by_source(corpus, "sop_v4") if "." not in p.locator}
    assert tops == {str(i) for i in range(1, 15)}


def test_sop_subsections_present(corpus) -> None:
    locs = {p.locator for p in _by_source(corpus, "sop_v4")}
    for loc in [
        "3.1",
        "3.2",
        "3.3",
        "4.1",
        "4.2",
        "4.3",
        "4.4",
        "4.5",
        "4.6",
        "5.1",
        "5.2",
        "5.3",
        "5.4",
        "5.5",
        "5.6",
        "8.1",
        "8.2",
    ]:
        assert loc in locs


def test_change_table_one_passage_per_row(corpus) -> None:
    rows = [p for p in _by_source(corpus, "sop_v4") if p.segment_kind == "table_row"]
    assert len(rows) == 11
    price = next(p for p in rows if p.meta["row_label"] == "Price tolerance")
    assert price.locator == "14"
    assert "₹1,000" in price.text and "₹500" in price.text


def test_tables_stay_inside_their_section(corpus) -> None:
    tds = next(p for p in _by_source(corpus, "sop_v4") if p.locator == "6")
    assert "| 194J | 10% |" in tds.text and "lower-deduction certificate" in tds.text
    approvals = next(p for p in _by_source(corpus, "sop_v4") if p.locator == "7")
    assert "Above ₹50 lakh" in approvals.text


def test_expected_counts(corpus) -> None:
    counts = Counter(p.source_id for p in corpus.passages)
    assert counts["faq_2023"] == 10
    assert counts["video_1"] == 9
    assert counts["shadowing"] == 9
    assert counts["di_03"] == 1 + 8  # parent + 8 steps
    assert counts["di_07"] == 1 + 6
    for memo in ("cm_inf_02", "cm_pha_01", "cm_ret_03"):
        assert counts[memo] == 1


@pytest.mark.parametrize(
    ("source_id", "prefix"), [("interview_1", "Interview 1"), ("interview_2", "Interview 2")]
)
def test_interview_turn_counts_match_transcript(corpus, source_id, prefix) -> None:
    """One passage per non-interviewer turn; count those turns straight from the docx."""
    blocks = read_blocks(get_settings().data_dir / "raw/PS-07_training_and_expert_transcripts.docx")
    answers, inside = 0, False
    for b in blocks:
        if b.kind == "heading":
            inside = b.text.startswith(prefix.replace("Interview", "Expert interview"))
        elif inside and re.match(r"^\[\d{2}:\d{2}\] (?!Interviewer:)", b.text):
            answers += 1
    assert answers > 0
    assert len(_by_source(corpus, source_id)) == answers


def test_questions_are_joined_to_answers(corpus) -> None:
    p = next(p for p in corpus.passages if p.locator == "Interview 1 [02:30]")
    assert p.text.startswith("Interviewer [02:15]: What do you know")
    assert "Tuesday noon" in p.text
    assert p.speaker == "Lakshmi"


def test_timestamps_preserved_exactly(corpus) -> None:
    turns = [p for p in corpus.passages if p.segment_kind == "turn"]
    assert turns
    for p in turns:
        assert re.search(r" \[\d{2}:\d{2}\]$", p.locator), p.locator
    locs = {p.locator for p in corpus.passages}
    assert {
        "Video 1 [04:30]",
        "Video 2 [03:40]",
        "Video 3 [10:20]",
        "Interview 2 [03:10]",
        "Shadowing 10:05",
        "Shadowing 12:15",
    } <= locs
    assert not any(re.search(r"(?<!\[)\b4:30\b", loc) for loc in locs)


def test_desk_instruction_and_memo_locators(corpus) -> None:
    locs = _locators(corpus)
    assert ("di_03", "Part A, step 4") in locs
    assert ("di_07", "Part B, step 3") in locs
    assert ("di_07", "Part B") in locs
    assert ("cm_inf_02", "Part C (CM-INF-02)") in locs
    assert ("cm_pha_01", "Part D (CM-PHA-01)") in locs
    assert ("faq_2023", "Part F") in locs
    step4 = next(p for p in corpus.passages if p.locator == "Part A, step 4")
    assert "variance panel" in step4.text


def test_client_scope_from_memos(corpus) -> None:
    scopes = {p.source_id: p.client_scope for p in corpus.passages}
    assert scopes["cm_inf_02"] == "infra"
    assert scopes["cm_pha_01"] == "pharma"
    assert scopes["cm_ret_03"] == "retail"
    assert scopes["sop_v4"] == "all"
    memo = next(p for p in corpus.passages if p.source_id == "cm_inf_02")
    assert str(memo.valid_to) == "2027-03-31"


def test_metadata_tables_become_source_metadata(corpus) -> None:
    assert corpus.source_meta["cm_inf_02"]["Valid until"] == "31 March 2027"
    assert corpus.source_meta["video_2"]["Recorded"] == "November 2022"
    assert corpus.source_meta["sop_v4"]["Replaces"].startswith("Version 3.1")
    assert not any("| Recorded |" in p.text or "| Reference |" in p.text for p in corpus.passages)
    assert not any(p.text.startswith("SYNTHETIC") for p in corpus.passages)


def test_context_header_format(corpus) -> None:
    p = next(p for p in corpus.passages if p.source_id == "sop_v4" and p.locator == "4.2")
    assert p.context_header == (
        "SOP v4.0 · §4.2 Price tolerance · effective 1 Apr 2026 · status current · all clients"
    )
    old = next(p for p in corpus.passages if p.source_id == "sop_v3_1" and p.locator == "3")
    assert "superseded" in old.context_header and old.source_status == "superseded"


def test_ids_unique_and_stable(pack, corpus) -> None:
    ids = [p.id for p in corpus.passages]
    assert len(ids) == len(set(ids))
    again = parse_corpus(pack, get_settings().data_dir)
    assert [(p.id, p.content_hash) for p in again.passages] == [
        (p.id, p.content_hash) for p in corpus.passages
    ]


def test_parents_link_children(corpus) -> None:
    by_id = {p.id: p for p in corpus.passages}
    step = next(p for p in corpus.passages if p.locator == "Part A, step 4")
    assert by_id[step.parent_id].locator == "Part A"
    sub = next(p for p in corpus.passages if p.source_id == "sop_v4" and p.locator == "4.2")
    assert by_id[sub.parent_id].locator == "4"


def test_no_sensitive_strings_in_passages(corpus) -> None:
    from app.core.redaction import contains_sensitive

    assert not [p.locator for p in corpus.passages if contains_sensitive(p.text)]


def test_planted_values_are_redacted_at_ingest(tmp_path, pack) -> None:
    d = docx.Document()
    d.add_heading("1. Bank details", level=1)
    d.add_paragraph("New a/c no. 123456789012, IFSC HDFC0001234, PAN ABCDE1234F, call 9876543210.")
    path = tmp_path / "planted.docx"
    d.save(str(path))
    spec = DocumentSpec(file="planted.docx", segmenter="numbered_sections", source="sop_v4")
    rows = finalise(segment_document(spec, read_blocks(path), pack).passages, pack)
    (row,) = rows
    for value in ("123456789012", "HDFC0001234", "ABCDE1234F", "9876543210"):
        assert value not in row.text
    assert row.meta["redactions"] == {"PAN": 1, "IFSC": 1, "ACCOUNT": 1, "PHONE": 1}
