"""Tests for PythonFileSession fuzzy path matching (v0.2.0 Phase 4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from duckdiff.exceptions import ConfigurationError
from duckdiff.python_file_session import PythonFileSession

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_from_text(tmp_path, a: str, b: str) -> PythonFileSession:
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text(a)
    f2.write_text(b)
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    return session


# ---------------------------------------------------------------------------
# suggest_path_mapping — validation
# ---------------------------------------------------------------------------


def test_suggest_path_mapping_requires_exactly_two_sources(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f3 = tmp_path / "c.py"
    for f in (f1, f2, f3):
        f.write_text("def foo():\n    return 1\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    session.add_source("c", f3)
    with pytest.raises(ConfigurationError):
        session.suggest_path_mapping()


def test_suggest_path_mapping_identical_files_returns_empty(tmp_path):
    session = _session_from_text(
        tmp_path,
        "def foo():\n    return 1\n",
        "def foo():\n    return 1\n",
    )
    assert session.suggest_path_mapping() == {}


def test_suggest_path_mapping_no_missing_returns_empty(tmp_path):
    """Files differ but no definitions are missing — nothing to rename."""
    session = _session_from_text(
        tmp_path,
        "def foo():\n    return 1\n",
        "def foo():\n    return 99\n",
    )
    assert session.suggest_path_mapping() == {}


# ---------------------------------------------------------------------------
# suggest_path_mapping — correct suggestions
# ---------------------------------------------------------------------------


def test_suggest_path_mapping_simple_rename(tmp_path):
    session = _session_from_text(
        tmp_path,
        "def process_data():\n    return 1\n",
        "def process_records():\n    return 1\n",
    )
    suggestions = session.suggest_path_mapping()
    assert "process_data" in suggestions
    assert suggestions["process_data"] == "process_records"


def test_suggest_path_mapping_no_match_below_threshold(tmp_path):
    """Completely unrelated names should not be suggested."""
    session = _session_from_text(
        tmp_path,
        "def foo():\n    return 1\n",
        "def completely_different_name():\n    return 1\n",
    )
    suggestions = session.suggest_path_mapping()
    assert suggestions == {}


def test_suggest_path_mapping_does_not_match_different_kinds(tmp_path):
    """A function should not be suggested as a rename of a class."""
    session = _session_from_text(
        tmp_path,
        "def process_data():\n    return 1\n",
        "class ProcessData:\n    pass\n",
    )
    suggestions = session.suggest_path_mapping()
    assert suggestions == {}


def test_suggest_path_mapping_no_double_booking(tmp_path):
    """One target path should not be suggested for two different sources."""
    session = _session_from_text(
        tmp_path,
        "def process_data():\n    return 1\n\ndef process_info():\n    return 2\n",
        "def process_records():\n    return 1\n",
    )
    suggestions = session.suggest_path_mapping()
    targets = list(suggestions.values())
    assert len(targets) == len(set(targets)), "double-booked target detected"


# ---------------------------------------------------------------------------
# apply_path_mapping
# ---------------------------------------------------------------------------


def test_apply_path_mapping_produces_renamed_status(tmp_path):
    session = _session_from_text(
        tmp_path,
        "def process_data():\n    return 1\n",
        "def process_records():\n    return 1\n",
    )
    mapping = {"process_data": "process_records"}
    result = session.apply_path_mapping(mapping)
    renamed = [d for d in result.definitions if d.status == "renamed"]
    assert len(renamed) == 1
    assert renamed[0].qualified_path == "process_records"
    assert renamed[0].renamed_from == "process_data"


def test_apply_path_mapping_body_unchanged(tmp_path):
    """Renamed function with identical body — body_changed should be False."""
    session = _session_from_text(
        tmp_path,
        "def process_data():\n    return 1\n",
        "def process_records():\n    return 1\n",
    )
    result = session.apply_path_mapping({"process_data": "process_records"})
    renamed = next(d for d in result.definitions if d.status == "renamed")
    assert renamed.body_changed is False
    assert renamed.signature_changed is False


def test_apply_path_mapping_body_changed(tmp_path):
    """Renamed function with different body — body_changed should be True."""
    session = _session_from_text(
        tmp_path,
        "def process_data():\n    return 1\n",
        "def process_records():\n    return 99\n",
    )
    result = session.apply_path_mapping({"process_data": "process_records"})
    renamed = next(d for d in result.definitions if d.status == "renamed")
    assert renamed.body_changed is True


def test_apply_path_mapping_renamed_count(tmp_path):
    session = _session_from_text(
        tmp_path,
        "def process_data():\n    return 1\n\ndef load_file():\n    return 2\n",
        "def process_records():\n    return 1\n\ndef load_document():\n    return 2\n",
    )
    mapping = {
        "process_data": "process_records",
        "load_file": "load_document",
    }
    result = session.apply_path_mapping(mapping)
    assert result.renamed == 2
    assert result.missing == 0


def test_apply_path_mapping_requires_two_sources(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f3 = tmp_path / "c.py"
    for f in (f1, f2, f3):
        f.write_text("def foo():\n    return 1\n")
    session = PythonFileSession()
    session.add_source("a", f1)
    session.add_source("b", f2)
    session.add_source("c", f3)
    with pytest.raises(ConfigurationError):
        session.apply_path_mapping({"foo": "foo"})


# ---------------------------------------------------------------------------
# CLI fuzzy flow
# ---------------------------------------------------------------------------


def test_cli_fuzzy_match_with_yes_shows_renamed(capsys, tmp_path):
    from duckdiff.cli import main
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def process_data():\n    return 1\n")
    f2.write_text("def process_records():\n    return 1\n")
    code = main(
        ["pyfile", f"a={f1}", f"b={f2}", "--fuzzy-match", "--yes"],
        input_func=lambda _: "y",
    )
    out = capsys.readouterr().out
    assert "process_data" in out
    assert "process_records" in out
    assert "renamed" in out.lower() or "↪" in out


def test_cli_fuzzy_match_without_flag_no_suggestion(capsys, tmp_path):
    from duckdiff.cli import main
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def process_data():\n    return 1\n")
    f2.write_text("def process_records():\n    return 1\n")
    main(["pyfile", f"a={f1}", f"b={f2}"])
    out = capsys.readouterr().out
    assert "↪" not in out
    assert "Suggested rename" not in out


def test_cli_fuzzy_match_no_suggestions_falls_back(capsys, tmp_path):
    """--fuzzy-match with no good matches falls back to normal missing output."""
    from duckdiff.cli import main
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n")
    f2.write_text("def completely_different():\n    return 1\n")
    main(["pyfile", f"a={f1}", f"b={f2}", "--fuzzy-match", "--yes"])
    out = capsys.readouterr().out
    assert "present in:" in out
    assert "↪" not in out