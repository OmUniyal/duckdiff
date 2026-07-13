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


def test_compare_raises_not_implemented_until_engine_lands(sample_csv_pair):
    left, right = sample_csv_pair
    session = ComparisonSession()
    session.add_source("left", left)
    session.add_source("right", right)
    with pytest.raises(NotImplementedError):
        session.compare(key_columns=["id"])


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
