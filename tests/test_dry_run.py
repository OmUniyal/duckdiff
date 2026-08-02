"""Tests for dry_run() -- schema introspection + file sizes, no row scanning."""

from __future__ import annotations

import pytest

from duckdiff.config import ComparisonConfig
from duckdiff.results import DryRunResult, SourcePreview
from duckdiff.session import ComparisonSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(paths: dict[str, str], config: ComparisonConfig | None = None) -> ComparisonSession:
    session = ComparisonSession(config)
    for name, path in paths.items():
        session.add_source(name, path)
    return session


# ---------------------------------------------------------------------------
# Return type and structure
# ---------------------------------------------------------------------------

def test_dry_run_returns_dry_run_result(sample_csv_pair):
    left, right = sample_csv_pair
    session = _make_session({"a": left, "b": right})
    result = session.dry_run()
    assert isinstance(result, DryRunResult)


def test_dry_run_sources_are_source_previews(sample_csv_pair):
    left, right = sample_csv_pair
    session = _make_session({"a": left, "b": right})
    result = session.dry_run()
    assert len(result.sources) == 2
    assert all(isinstance(s, SourcePreview) for s in result.sources)


def test_dry_run_source_names(sample_csv_pair):
    left, right = sample_csv_pair
    session = _make_session({"a": left, "b": right})
    result = session.dry_run()
    names = [s.name for s in result.sources]
    assert names == ["a", "b"]


def test_dry_run_source_paths(sample_csv_pair):
    left, right = sample_csv_pair
    session = _make_session({"a": left, "b": right})
    result = session.dry_run()
    assert result.sources[0].path == left
    assert result.sources[1].path == right


def test_dry_run_file_sizes_are_positive(sample_csv_pair):
    left, right = sample_csv_pair
    session = _make_session({"a": left, "b": right})
    result = session.dry_run()
    assert all(s.file_size_bytes > 0 for s in result.sources)


def test_dry_run_file_size_matches_disk(sample_csv_pair):
    import os
    left, right = sample_csv_pair
    session = _make_session({"a": left, "b": right})
    result = session.dry_run()
    assert result.sources[0].file_size_bytes == os.path.getsize(left)
    assert result.sources[1].file_size_bytes == os.path.getsize(right)


def test_dry_run_columns_detected(sample_csv_pair):
    left, right = sample_csv_pair
    session = _make_session({"a": left, "b": right})
    result = session.dry_run()
    assert result.sources[0].columns == ["id", "name", "amount"]
    assert result.sources[1].columns == ["id", "name", "amount"]


# ---------------------------------------------------------------------------
# Schema-compatible sources
# ---------------------------------------------------------------------------

def test_dry_run_no_error_on_matching_schema(sample_csv_pair):
    left, right = sample_csv_pair
    session = _make_session({"a": left, "b": right})
    result = session.dry_run()
    assert result.would_raise is None


def test_dry_run_comparison_columns_on_matching_schema(sample_csv_pair):
    left, right = sample_csv_pair
    session = _make_session({"a": left, "b": right})
    result = session.dry_run()
    assert result.comparison_columns == ["id", "name", "amount"]


def test_dry_run_no_warnings_on_clean_match(sample_csv_pair):
    left, right = sample_csv_pair
    session = _make_session({"a": left, "b": right})
    result = session.dry_run()
    assert result.warnings == []


def test_dry_run_comparison_columns_respect_ignore(sample_csv_pair):
    left, right = sample_csv_pair
    config = ComparisonConfig(ignore_columns=["name"])
    session = _make_session({"a": left, "b": right}, config)
    result = session.dry_run()
    assert "name" not in result.comparison_columns
    assert result.would_raise is None


# ---------------------------------------------------------------------------
# Schema-incompatible sources (would_raise)
# ---------------------------------------------------------------------------

def test_dry_run_captures_schema_mismatch(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,amount\n1,10\n")
    b.write_text("id,value\n1,10\n")  # 'amount' vs 'value'
    session = _make_session({"a": str(a), "b": str(b)})
    result = session.dry_run()
    assert result.would_raise is not None
    assert "amount" in result.would_raise or "value" in result.would_raise


def test_dry_run_does_not_raise_on_schema_mismatch(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,amount\n1,10\n")
    b.write_text("id,value\n1,10\n")
    session = _make_session({"a": str(a), "b": str(b)})
    # Must not raise -- would_raise captures it instead
    result = session.dry_run()
    assert isinstance(result, DryRunResult)


def test_dry_run_comparison_columns_empty_on_mismatch(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,amount\n1,10\n")
    b.write_text("id,value\n1,10\n")
    session = _make_session({"a": str(a), "b": str(b)})
    result = session.dry_run()
    assert result.comparison_columns == []


def test_dry_run_sources_still_populated_on_mismatch(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,amount\n1,10\n")
    b.write_text("id,value\n1,10\n")
    session = _make_session({"a": str(a), "b": str(b)})
    result = session.dry_run()
    # Even when schema errors, source metadata is always populated
    assert len(result.sources) == 2


# ---------------------------------------------------------------------------
# Auto-intersect interaction
# ---------------------------------------------------------------------------

def test_dry_run_auto_intersect_resolves_mismatch(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,amount,extra_a\n1,10,x\n")
    b.write_text("id,amount,extra_b\n1,10,y\n")
    config = ComparisonConfig(auto_intersect_columns=True)
    session = _make_session({"a": str(a), "b": str(b)}, config)
    result = session.dry_run()
    assert result.would_raise is None
    assert "id" in result.comparison_columns
    assert "amount" in result.comparison_columns
    assert "extra_a" not in result.comparison_columns
    assert "extra_b" not in result.comparison_columns


def test_dry_run_auto_intersect_produces_warnings(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("id,amount,extra_a\n1,10,x\n")
    b.write_text("id,amount,extra_b\n1,10,y\n")
    config = ComparisonConfig(auto_intersect_columns=True)
    session = _make_session({"a": str(a), "b": str(b)}, config)
    result = session.dry_run()
    assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# Guard: requires at least 2 sources
# ---------------------------------------------------------------------------

def test_dry_run_requires_two_sources(tmp_path):
    a = tmp_path / "a.csv"
    a.write_text("id,amount\n1,10\n")
    session = ComparisonSession()
    session.add_source("a", str(a))
    with pytest.raises(ValueError, match="2 sources"):
        session.dry_run()


# ---------------------------------------------------------------------------
# N-way (3 sources)
# ---------------------------------------------------------------------------

def test_dry_run_three_sources(tmp_path):
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.csv").write_text("id,amount\n1,10\n")
    session = _make_session({
        "a": str(tmp_path / "a.csv"),
        "b": str(tmp_path / "b.csv"),
        "c": str(tmp_path / "c.csv"),
    })
    result = session.dry_run()
    assert len(result.sources) == 3
    assert result.would_raise is None
    assert result.comparison_columns == ["id", "amount"]