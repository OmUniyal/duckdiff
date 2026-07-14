import pytest

from duckdiff.schema import suggest_column_mapping


def test_no_suggestions_when_schemas_already_match():
    source_columns = {
        "a": ["id", "name", "amount"],
        "b": ["id", "name", "amount"],
    }
    assert suggest_column_mapping(source_columns) == {}


def test_suggests_mapping_for_realistic_renames():
    """These are the exact pairs that motivated lowering the default
    threshold from 0.85 to 0.6 -- see schema.py's docstring."""
    source_columns = {
        "legacy": ["customer_id", "amount", "phone"],
        "new": ["cust_id", "amt", "telephone"],
    }
    result = suggest_column_mapping(source_columns)
    assert result == {
        "new": {
            "cust_id": "customer_id",
            "amt": "amount",
            "telephone": "phone",
        }
    }


def test_common_columns_excluded_even_if_also_similar_to_something_else():
    """'id' matches exactly across both sources, so it should never appear
    as a suggestion target or candidate, even though nothing here is
    "close" enough in spelling to confuse it with anything else."""
    source_columns = {
        "a": ["id", "customer_id"],
        "b": ["id", "cust_id"],
    }
    result = suggest_column_mapping(source_columns)
    assert result == {"b": {"cust_id": "customer_id"}}
    assert "id" not in result.get("b", {})


def test_dissimilar_columns_get_no_suggestion():
    source_columns = {
        "a": ["amount"],
        "b": ["region"],
    }
    assert suggest_column_mapping(source_columns) == {}


def test_threshold_controls_recall_vs_precision():
    """'email' vs 'email_address' sits right at the edge (~0.59) --
    demonstrates the tuning knob directly rather than asserting an
    opaque float."""
    source_columns = {
        "a": ["email"],
        "b": ["email_address"],
    }
    assert suggest_column_mapping(source_columns, threshold=0.7) == {}
    assert suggest_column_mapping(source_columns, threshold=0.5) == {
        "b": {"email_address": "email"}
    }


def test_case_and_separator_insensitive():
    source_columns = {
        "a": ["customer_id"],
        "b": ["CustomerID"],
    }
    result = suggest_column_mapping(source_columns)
    assert result == {"b": {"CustomerID": "customer_id"}}


def test_greedy_assignment_does_not_double_book_a_target():
    """Two candidates are both similar to the same reference column;
    only the better-scoring one should claim it, and the loser gets no
    suggestion at all rather than a second-best guess -- a wrong
    silent guess is worse than no suggestion here."""
    source_columns = {
        "a": ["amount"],
        "b": ["amount_usd", "amt"],  # both plausibly "amount"
    }
    result = suggest_column_mapping(source_columns, threshold=0.5)
    assert result["b"] == {"amount_usd": "amount"}
    assert "amt" not in result["b"]


def test_three_way_matches_each_source_against_the_reference_independently():
    source_columns = {
        "a": ["customer_id", "amount"],
        "b": ["cust_id", "amount"],
        "c": ["customerid", "amount"],
    }
    result = suggest_column_mapping(source_columns)
    assert result == {
        "b": {"cust_id": "customer_id"},
        "c": {"customerid": "customer_id"},
    }


def test_reference_source_never_appears_as_a_key():
    source_columns = {
        "a": ["customer_id"],
        "b": ["cust_id"],
    }
    result = suggest_column_mapping(source_columns)
    assert "a" not in result


def test_requires_at_least_two_sources():
    with pytest.raises(ValueError, match="at least 2 sources"):
        suggest_column_mapping({"a": ["id"]})


def test_invalid_threshold_raises():
    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        suggest_column_mapping({"a": ["id"], "b": ["id"]}, threshold=1.5)