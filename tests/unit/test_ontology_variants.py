"""Schema: an attribute may be marked as a client-specific version of another."""

from __future__ import annotations

import pytest

from app.graph.ontology import Ontology


def _onto(variant_of: str | None, value_type: str = "percentage") -> dict:
    return {
        "name": "t",
        "topics": [{"key": "tol", "label": "Tolerance"}],
        "attributes": [
            {"key": "tol.general", "topic": "tol", "label": "General", "value_type": "percentage"},
            {
                "key": "tol.client_x",
                "topic": "tol",
                "label": "Client X",
                "value_type": value_type,
                "variant_of": variant_of,
            },
        ],
    }


def test_variant_of_a_peer_attribute_is_accepted() -> None:
    onto = Ontology.model_validate(_onto("tol.general"))
    assert onto.attribute("tol.client_x").variant_of == "tol.general"
    assert Ontology.model_validate(_onto(None)).attribute("tol.client_x").variant_of is None


@pytest.mark.parametrize(
    ("variant_of", "value_type"),
    [("tol.missing", "percentage"), ("tol.client_x", "percentage"), ("tol.general", "money")],
)
def test_variant_of_must_name_another_attribute_of_the_same_type(variant_of, value_type) -> None:
    with pytest.raises(ValueError, match="variant_of"):
        Ontology.model_validate(_onto(variant_of, value_type))
