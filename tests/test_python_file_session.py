"""Tests for PythonFileSession (v0.2.0 Phase 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from duckdiff.exceptions import ConfigurationError, DuckDiffError
from duckdiff.python_file_session import PythonFileSession

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session(*fixture_names: str) -> PythonFileSession:
    """Build a session from fixture filenames, labelled a, b, c ..."""
    session = PythonFileSession()
    for label, name in zip("abcdefgh", fixture_names):
        session.add_source(label, FIXTURES / name)
    return session


def _diff(session: PythonFileSession, qpath: str):
    result = session.compare()
    matches = [d for d in result.definitions if d.qualified_path == qpath]
    assert matches, f"No DefinitionDiff for {qpath!r}"
    return matches[0]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_fewer_than_two_sources_raises():
    session = PythonFileSession()
    session.add_source("a", FIXTURES / "plain_script.py")
    with pytest.raises(ConfigurationError):
        session.compare()


def test_zero_sources_raises():
    with pytest.raises(ConfigurationError):
        PythonFileSession().compare()


def test_nonexistent_path_raises():
    session = PythonFileSession()
    with pytest.raises(DuckDiffError):
        session.add_source("a", "/nonexistent/path/foo.py")


def test_non_py_file_raises(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("a,b\n1,2\n")
    session = PythonFileSession()
    with pytest.raises(DuckDiffError):
        session.add_source("a", f)


def test_duplicate_label_raises():
    session = PythonFileSession()
    session.add_source("a", FIXTURES / "plain_script.py")
    with pytest.raises(ConfigurationError):
        session.add_source("a", FIXTURES / "oop_script.py")


# ---------------------------------------------------------------------------
# Phase A — identical files
# ---------------------------------------------------------------------------


def test_identical_files_returns_files_identical():
    session = _session("plain_script.py", "plain_script.py")
    result = session.compare()
    assert result.files_identical is True
    assert result.definitions == []


def test_identical_files_has_correct_hashes():
    session = _session("plain_script.py", "plain_script.py")
    result = session.compare()
    assert result.file_hashes["a"] == result.file_hashes["b"]


def test_different_files_not_identical():
    session = _session("plain_script.py", "oop_script.py")
    result = session.compare()
    assert result.files_identical is False


# ---------------------------------------------------------------------------
# Phase B — definition drill-down
# ---------------------------------------------------------------------------


def test_changed_body_detected(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n")
    f2.write_text("def foo():\n    return 2\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    result = session.compare()
    diff = next(d for d in result.definitions if d.qualified_path == "foo")
    assert diff.status == "changed"
    assert diff.body_changed is True
    assert diff.signature_changed is False


def test_changed_signature_detected(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo(x: int) -> int:\n    return x\n")
    f2.write_text("def foo(value: int) -> int:\n    return value\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    diff = _diff(session, "foo")
    assert diff.status == "changed"
    assert diff.signature_changed is True


def test_changed_both_sig_and_body(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo(x: int) -> int:\n    return x\n")
    f2.write_text("def foo(x: int, y: int) -> int:\n    return x + y\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    diff = _diff(session, "foo")
    assert diff.signature_changed is True
    assert diff.body_changed is True


def test_unchanged_function(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
    f2.write_text("def foo():\n    return 1\n\ndef bar():\n    return 99\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    diff = _diff(session, "foo")
    assert diff.status == "unchanged"


def test_missing_function_detected(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
    f2.write_text("def foo():\n    return 1\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    diff = _diff(session, "bar")
    assert diff.status == "missing"
    assert "a" in diff.present_in


def test_missing_present_in_lists_correct_labels(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f3 = tmp_path / "c.py"
    f1.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
    f2.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
    f3.write_text("def foo():\n    return 1\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    session.add_source("c", f3)
    diff = _diff(session, "bar")
    assert diff.status == "missing"
    assert "a" in diff.present_in
    assert "b" in diff.present_in
    assert "c" not in diff.present_in


def test_counts_are_correct(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text(
        "def foo():\n    return 1\n\n"
        "def bar():\n    return 2\n\n"
        "def baz():\n    return 3\n"
    )
    f2.write_text(
        "def foo():\n    return 1\n\n"   # unchanged
        "def bar():\n    return 99\n\n"  # changed
        # baz missing
    )
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    result = session.compare()
    assert result.unchanged == 1
    assert result.changed == 1
    assert result.missing == 1


def test_order_only_flag(tmp_path):
    """Files with same definitions in different order → order_only=True."""
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
    f2.write_text("def bar():\n    return 2\n\ndef foo():\n    return 1\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    result = session.compare()
    assert result.files_identical is False
    assert result.order_only is True
    assert result.changed == 0
    assert result.missing == 0


def test_order_only_false_when_changes_exist(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
    f2.write_text("def bar():\n    return 2\n\ndef foo():\n    return 99\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    result = session.compare()
    assert result.order_only is False


def test_nested_function_change_detected(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text(
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner()\n"
    )
    f2.write_text(
        "def outer():\n"
        "    def inner():\n"
        "        return 99\n"
        "    return inner()\n"
    )
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    result = session.compare()
    inner_diff = next(
        (d for d in result.definitions if d.qualified_path == "outer.inner"), None
    )
    assert inner_diff is not None
    assert inner_diff.status == "changed"


def test_file_hashes_keyed_by_label(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n")
    f2.write_text("def foo():\n    return 2\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    result = session.compare()
    assert set(result.file_hashes.keys()) == {"a", "b"}


def test_n_way_three_sources(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f3 = tmp_path / "c.py"
    f1.write_text("def foo():\n    return 1\n")
    f2.write_text("def foo():\n    return 1\n")
    f3.write_text("def foo():\n    return 99\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    session.add_source("c", f3)
    result = session.compare()
    diff = next(d for d in result.definitions if d.qualified_path == "foo")
    assert diff.status == "changed"
    assert result.changed == 1