"""Tests for suggest_key_columns() -- candidate key discovery for a single source."""

from __future__ import annotations

import pytest

from duckdiff.results import KeyColumnSuggestion
from duckdiff.session import ComparisonSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_with(path: str) -> ComparisonSession:
    session = ComparisonSession()
    session.add_source("a", path)
    return session


# ---------------------------------------------------------------------------
# Return type and structure
# ---------------------------------------------------------------------------

def test_returns_list_of_key_column_suggestions(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,name\n1,alice\n2,bob\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    assert isinstance(result, list)
    assert all(isinstance(s, KeyColumnSuggestion) for s in result)


def test_suggestion_fields_populated(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,name\n1,alice\n2,bob\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    for s in result:
        assert isinstance(s.columns, list)
        assert len(s.columns) >= 1
        assert isinstance(s.distinct_count, int)
        assert isinstance(s.total_count, int)
        assert isinstance(s.is_unique, bool)


def test_total_count_matches_row_count(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,name\n1,alice\n2,bob\n3,carol\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    assert all(s.total_count == 3 for s in result)


def test_sorted_by_distinct_count_descending(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,name,city\n1,alice,london\n2,alice,paris\n3,bob,london\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    counts = [s.distinct_count for s in result]
    assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# Single-column unique key
# ---------------------------------------------------------------------------

def test_single_unique_column_found(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,name\n1,alice\n2,bob\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    unique = [s for s in result if s.is_unique]
    assert any(s.columns == ["id"] for s in unique)


def test_unique_key_is_unique_flag_true(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,name\n1,alice\n2,bob\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    for s in result:
        if s.columns == ["id"]:
            assert s.is_unique is True
            assert s.distinct_count == s.total_count


def test_non_unique_column_is_unique_flag_false(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,city\n1,london\n2,london\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    for s in result:
        if s.columns == ["city"]:
            assert s.is_unique is False
            assert s.distinct_count < s.total_count


# ---------------------------------------------------------------------------
# Composite key
# ---------------------------------------------------------------------------

def test_composite_key_found_when_no_single_column_unique(tmp_path):
    f = tmp_path / "a.csv"
    # Neither store_code nor month is unique alone; together they are
    f.write_text("store_code,month,sales\n"
                 "A,Jan,100.0\nA,Feb,200.0\nB,Jan,150.0\nB,Feb,250.0\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    unique = [s for s in result if s.is_unique]
    assert any(sorted(s.columns) == ["month", "store_code"] for s in unique)


def test_stops_at_first_unique_size(tmp_path):
    f = tmp_path / "a.csv"
    # id is unique on its own — should not test pairs
    f.write_text("id,city\n1,london\n2,paris\n3,berlin\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    # No combo of size 2 should appear if a size-1 unique key was found
    assert all(len(s.columns) == 1 for s in result)


# ---------------------------------------------------------------------------
# Measure column exclusion
# ---------------------------------------------------------------------------

def test_measure_columns_excluded(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,revenue,quantity\n1,100.0,5.0\n2,200.0,10.0\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    all_tested_cols = {col for s in result for col in s.columns}
    assert "revenue" not in all_tested_cols
    assert "quantity" not in all_tested_cols


def test_measure_exclusion_does_not_prevent_finding_key(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,amount\n1,10\n2,20\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    unique = [s for s in result if s.is_unique]
    assert len(unique) >= 1
    assert unique[0].columns == ["id"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_unknown_source_raises(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,name\n1,alice\n")
    session = _session_with(str(f))
    with pytest.raises(ValueError, match="not registered"):
        session.suggest_key_columns("z")


def test_all_columns_non_unique_returns_non_empty_list(tmp_path):
    f = tmp_path / "a.csv"
    # Every column has duplicates -- no unique key at size 1
    f.write_text("city,country\nlondon,uk\nparis,france\nlondon,france\n")
    session = _session_with(str(f))
    result = session.suggest_key_columns("a")
    # Should still return candidates, just none with is_unique=True at size 1
    assert len(result) > 0


def test_parquet_source(tmp_path):
    pytest.importorskip("pyarrow")
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.table({"id": [1, 2, 3], "name": ["alice", "bob", "carol"]})
    pq_path = str(tmp_path / "a.parquet")
    pq.write_table(table, pq_path)
    session = _session_with(pq_path)
    result = session.suggest_key_columns("a")
    unique = [s for s in result if s.is_unique]
    assert len(unique) >= 1