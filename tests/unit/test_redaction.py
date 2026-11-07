from __future__ import annotations

import pytest

from app.core.redaction import contains_sensitive, redact, redact_with_counts

# Fake values planted for the test; none of them belong to anyone.
PAN = "ABCDE1234F"
IFSC = "HDFC0001234"


@pytest.mark.parametrize(
    ("text", "label"),
    [
        (f"Supplier PAN is {PAN}.", "PAN"),
        (f"IFSC {IFSC} for the new account", "IFSC"),
        ("Please update a/c no. 123456789012 today", "ACCOUNT"),
        ("Account number: 0012 3456 7890 12", "ACCOUNT"),
        ("Call me on +91 98765 43210 to verify", "PHONE"),
        ("Call 9876543210 for verification", "PHONE"),
        ("reach ravi.k@example.com for details", "EMAIL"),
    ],
)
def test_sensitive_values_are_redacted(text: str, label: str) -> None:
    result = redact_with_counts(text)
    assert result.counts.get(label) == 1, result
    assert f"[REDACTED_{label}]" in result.text


@pytest.mark.parametrize(
    "text",
    [
        "Supplier GSTIN 27ABCDE1234F1Z5 is active",  # GSTIN embeds a PAN but is public
        "Excess ₹2,500 on a ₹1,97,500 line; limit ₹500",
        "Software support ₹4,80,000 at 2% = ₹9,600",
        "Invoice TR/2026/0881/A vs TR/2026/881",
        "Interview 1 [02:30] and Shadowing 10:05",
        "AATO above ₹5 crore; approvals above ₹10 lakh and ₹50 lakh",
        "Lakshmi leaves Meridian on 14 November 2026",
    ],
)
def test_business_text_is_untouched(text: str) -> None:
    assert redact(text) == text
    assert not contains_sensitive(text)


def test_multiple_values_in_one_message() -> None:
    text = f"PAN {PAN}, IFSC {IFSC}, a/c 98765432101, phone 9123456780"
    result = redact_with_counts(text)
    assert result.counts == {"PAN": 1, "IFSC": 1, "ACCOUNT": 1, "PHONE": 1}
    assert PAN not in result.text and IFSC not in result.text
