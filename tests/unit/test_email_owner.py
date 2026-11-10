"""Emails: who sent them, and when a sender counts as a client's registered owner."""

from __future__ import annotations

from app.govern.policy import owns_client
from app.graph.ontology import Ontology, SenderAuthority
from app.ingest.connectors import from_upload

EML = (
    b"From: Financial Controller, Client X <fc@client-x.example>\r\n"
    b"To: Process team <team@example.com>\r\n"
    b"Subject: Tolerance update\r\n"
    b"Date: Mon, 2 Nov 2026 10:14:00 +0530\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"From 16 November the tolerance is 7%.\r\n"
)


def test_an_uploaded_email_is_read_as_an_email_with_its_sender() -> None:
    [ep] = from_upload("update.eml", EML)
    assert ep.sender == "fc@client-x.example"
    assert ep.sender_role == "Financial Controller, Client X"
    assert ep.received_at.date().isoformat() == "2026-11-02"


def test_an_uploader_is_judged_never_the_header_they_carry() -> None:
    [ep] = from_upload("update.eml", EML, sender="processor@example.com")
    assert ep.sender == "processor@example.com" and ep.sender_role is None
    [ep] = from_upload("update.eml", EML, sender="p@example.com", sender_role="processor")
    assert ep.sender_role == "processor"


def test_owner_of_one_client_only() -> None:
    onto = Ontology(
        name="t",
        sender_authority=[
            SenderAuthority(who="Financial Controller, Client X", client="Client X"),
            SenderAuthority(who="Process team", client="all", topics=["all"]),
        ],
    )
    fc = "Financial Controller, Client X"
    assert owns_client(onto, "fc@client-x.example", fc, "Client X")
    assert not owns_client(onto, "fc@client-x.example", fc, "Client Y")
    assert not owns_client(onto, "team@example.com", "Process team", "Client X")  # global grant
    assert not owns_client(onto, None, None, "Client X")


def test_a_grant_names_a_client_by_its_short_name() -> None:
    from app.govern.policy import same_client

    assert same_client("Arvana Retail", "Arvana Retail Pvt Ltd")
    assert same_client("Arvana Retail Pvt Ltd", "Arvana Retail")
    assert not same_client("Arvana Retail", "Arvana Pharma")
    assert not same_client("", "Arvana Pharma")


def test_forwards_of_one_message_share_its_identity() -> None:
    from pathlib import Path

    from app.ingest.triage import message_key, original_text

    root = Path(__file__).resolve().parents[2] / "synthetic" / "emails"
    key = message_key((root / "01_infra_bulk_tolerance.eml").read_bytes())
    assert key and key == message_key((root / "04_fwd_infra_bulk_tolerance.eml").read_bytes())
    assert key == message_key((root / "05_fwd_fwd_infra_bulk_tolerance.eml").read_bytes())
    assert key != message_key((root / "02_price_tolerance_still_2pct.eml").read_bytes())
    quoted = "Thanks!\n\n-----Original Message-----\nFrom: A\nSubject: x\n\n> Pay on Friday."
    assert original_text(quoted) == "pay on friday."
