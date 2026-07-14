import duckdb
import pytest

from duckdiff.session import ComparisonSession


def test_add_source_registers_path(sample_csv_pair):
    left, right = sample_csv_pair
    session = ComparisonSession()
    session.add_source("left", left)
    session.add_source("right", right)
    assert session._sources == {"left": left, "right": right}


def test_add_source_returns_self_for_chaining(sample_csv_pair):
    left, right = sample_csv_pair
    session = ComparisonSession()
    result = session.add_source("left", left).add_source("right", right)
    assert result is session


def test_add_duplicate_source_raises(sample_csv_pair):
    left, _ = sample_csv_pair
    session = ComparisonSession()
    session.add_source("left", left)
    with pytest.raises(ValueError):
        session.add_source("left", left)


def test_compare_requires_at_least_two_sources(sample_csv_pair):
    left, _ = sample_csv_pair
    session = ComparisonSession()
    session.add_source("left", left)
    with pytest.raises(ValueError):
        session.compare()


def test_compare_runs_end_to_end_through_the_session(sample_csv_pair):
    """left/right differ only on id=2's amount -- confirms the session wires
    add_source() -> compare() -> run_comparison() correctly, not just that
    the comparator works in isolation (see test_comparator.py for that)."""
    left, right = sample_csv_pair
    session = ComparisonSession()
    session.add_source("left", left)
    session.add_source("right", right)
    result = session.compare(key_columns=["id"])
    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 1


def test_context_manager_closes_connection(sample_csv_pair):
    left, right = sample_csv_pair
    with ComparisonSession() as session:
        session.add_source("left", left)
        session.add_source("right", right)
    # Connection should be closed after exiting the context; DuckDB raises
    # ConnectionException on use-after-close, which is the behavior we're
    # relying on.
    with pytest.raises(duckdb.ConnectionException):
        session._connection.execute("SELECT 1")
