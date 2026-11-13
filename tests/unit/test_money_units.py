"""Money amounts are stored in the base currency even when the unit names the multiple and the
currency together (an extractor writing "thousand EUR" for "EUR 10 thousand")."""

from __future__ import annotations

import pytest

from app.graph.extract import XValue, money_multiplier, normalise_value
from app.graph.ontology import Ontology

ONTO = Ontology(
    name="t",
    base_currency="EUR",
    units={"thousand": 1000.0, "million": 1_000_000.0, "euro": 1.0, "€": 1.0, "working day": 1.0},
)


@pytest.mark.parametrize(
    ("unit", "mult"),
    [
        ("thousand", 1000.0),  # a unit word on its own
        ("EUR", 1.0),  # the base currency code
        ("thousand EUR", 1000.0),  # multiple + currency, either order
        ("EUR million", 1_000_000.0),
        ("thousand euros", 1000.0),  # plural currency word
        ("€ thousand", 1000.0),
        ("Thousand.", 1000.0),
        ("thousand USD", None),  # another currency: never converted silently
        ("thousand widgets", None),  # an unknown word: kept as written
        ("", None),
    ],
)
def test_money_multiplier(unit: str, mult: float | None) -> None:
    assert money_multiplier(unit, ONTO) == mult


def test_amount_with_multiple_and_currency_is_stored_in_base_currency() -> None:
    v = normalise_value(
        XValue(type="money", number=10, unit="thousand EUR", text="EUR 10k"), ONTO, None
    )
    assert v["number"] == 10_000 and v["unit"] == "EUR"
    assert v["as_written"] == {"number": 10, "unit": "thousand EUR"}


def test_unknown_unit_is_left_as_written() -> None:
    v = normalise_value(
        XValue(type="money", number=10, unit="thousand USD", text="USD 10k"), ONTO, None
    )
    assert v["number"] == 10 and "as_written" not in v


def _draft(text: str, vtype: str = "enum", client: str | None = None, cond: str | None = None):
    from app.graph.extract import Draft

    return Draft(
        origin_key=f"p:{text}",
        attribute="runs.day",
        topic="runs",
        about="Payment runs",
        about_type=None,
        value={"type": vtype, "text": text, "items": None},
        client=client,
        scope={"client": client} if client else {},
        condition=cond,
        kind="rule",
        statement=f"Runs are on {text}.",
        quote=f"on {text}",
        quote_verified=True,
        asserted_from=None,
        asserted_to=None,
        passage_id="p",
        source_id="s",
        episode_id="e",
    )


def test_values_of_one_list_attribute_in_one_passage_become_one_fact() -> None:
    from app.graph.extract import merge_list_values

    (d,) = merge_list_values([_draft("Tuesday"), _draft("Friday")])
    assert d.value["items"] == ["Tuesday", "Friday"] and d.value["text"] == "Tuesday and Friday"
    assert d.statement == "Runs are on Tuesday. Runs are on Friday." and d.quote_verified


def test_numbers_other_scopes_and_conditions_are_not_merged() -> None:
    from app.graph.extract import merge_list_values

    nums = [_draft("2", "number"), _draft("3", "number")]
    assert len(merge_list_values(nums)) == 2  # a real conflict stays visible
    scoped = [_draft("Tuesday"), _draft("Friday", client="Client B")]
    assert len(merge_list_values(scoped)) == 2
    cond = [_draft("Tuesday"), _draft("Friday", cond="in March")]
    assert len(merge_list_values(cond)) == 2
