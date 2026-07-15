import duckdb
import pytest

from duckdiff.config import ComparisonConfig
from duckdiff.exceptions import ConfigurationError
from duckdiff.session import ComparisonSession


def _write_csv(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("\n".join(rows) + "\n")
    return str(path)


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


# ---------------------------------------------------------------------------
# Fuzzy column mapping (Phase 2)
# ---------------------------------------------------------------------------


def test_suggest_column_mapping_reads_real_file_headers(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0"])
    session = ComparisonSession()
    session.add_source("a", a)
    session.add_source("b", b)
    suggestion = session.suggest_column_mapping()
    assert suggestion == {"b": {"cust_id": "customer_id"}}


def test_suggest_column_mapping_requires_two_sources(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    session = ComparisonSession()
    session.add_source("a", a)
    with pytest.raises(ValueError, match="at least 2 sources"):
        session.suggest_column_mapping()


def test_suggest_column_mapping_never_mutates_config(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0"])
    session = ComparisonSession()
    session.add_source("a", a)
    session.add_source("b", b)
    session.suggest_column_mapping()
    assert session._column_mapping == {}
    assert session.config.enable_fuzzy_column_mapping is False


def test_apply_column_mapping_requires_flag_enabled(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0"])
    session = ComparisonSession()  # enable_fuzzy_column_mapping defaults to False
    session.add_source("a", a)
    session.add_source("b", b)
    with pytest.raises(ConfigurationError, match="enable_fuzzy_column_mapping"):
        session.apply_column_mapping({"b": {"cust_id": "customer_id"}})


def test_apply_column_mapping_rejects_unknown_source(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(enable_fuzzy_column_mapping=True)
    session = ComparisonSession(config)
    session.add_source("a", a)
    session.add_source("b", b)
    with pytest.raises(ValueError, match="unknown source"):
        session.apply_column_mapping({"nonexistent": {"x": "y"}})


def test_apply_column_mapping_returns_self_for_chaining(tmp_path):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    config = ComparisonConfig(enable_fuzzy_column_mapping=True)
    session = ComparisonSession(config)
    session.add_source("a", a)
    session.add_source("b", b)
    result = session.apply_column_mapping({})
    assert result is session


def test_compare_uses_applied_mapping_end_to_end(tmp_path):
    """The full workflow: suggest, review, apply, compare -- with genuinely
    mismatched column names that would otherwise raise SchemaMismatchError."""
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0", "2,25.0"])
    config = ComparisonConfig(enable_fuzzy_column_mapping=True)
    session = ComparisonSession(config)
    session.add_source("a", a)
    session.add_source("b", b)

    suggestion = session.suggest_column_mapping()
    session.apply_column_mapping(suggestion)

    result = session.compare(key_columns=["customer_id"])
    assert result.matched_row_count == 1
    assert result.mismatched_row_count == 1