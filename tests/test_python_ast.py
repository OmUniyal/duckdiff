"""Tests for src/duckdiff/extractors/python_ast.py"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from duckdiff.extractors.python_ast import (
    DefinitionRow,
    extract_definitions,
    file_hash,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(rows: list[DefinitionRow], qpath: str) -> DefinitionRow:
    """Fetch a row by qualified_path; fail clearly if missing."""
    matches = [r for r in rows if r.qualified_path == qpath]
    assert matches, f"No row with qualified_path={qpath!r}. Got: {[r.qualified_path for r in rows]}"
    return matches[0]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# file_hash tests
# ---------------------------------------------------------------------------


def test_file_hash_is_deterministic():
    h1 = file_hash(FIXTURES / "plain_script.py")
    h2 = file_hash(FIXTURES / "plain_script.py")
    assert h1 == h2


def test_file_hash_differs_across_files():
    h1 = file_hash(FIXTURES / "plain_script.py")
    h2 = file_hash(FIXTURES / "oop_script.py")
    assert h1 != h2


def test_file_hash_empty_file():
    h = file_hash(FIXTURES / "empty_script.py")
    assert isinstance(h, str) and len(h) == 64


def test_file_hash_ignores_comments_and_whitespace(tmp_path):
    """Two files identical except for comments/whitespace must share the same hash."""
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n")
    f2.write_text("# this is a comment\ndef foo():\n\n    return 1\n\n")
    assert file_hash(f1) == file_hash(f2)


def test_file_hash_changes_on_body_change(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n")
    f2.write_text("def foo():\n    return 2\n")
    assert file_hash(f1) != file_hash(f2)


# ---------------------------------------------------------------------------
# extract_definitions — empty file
# ---------------------------------------------------------------------------


def test_empty_file_returns_empty_list():
    rows = extract_definitions(FIXTURES / "empty_script.py")
    assert rows == []


# ---------------------------------------------------------------------------
# extract_definitions — plain_script.py
# ---------------------------------------------------------------------------


def test_plain_script_has_module_statements_row():
    rows = extract_definitions(FIXTURES / "plain_script.py")
    qpaths = [r.qualified_path for r in rows]
    assert "<module_statements>" in qpaths


def test_plain_script_top_level_functions_present():
    rows = extract_definitions(FIXTURES / "plain_script.py")
    qpaths = [r.qualified_path for r in rows]
    assert "load_config" in qpaths
    assert "process_records" in qpaths
    assert "main" in qpaths


def test_plain_script_nested_function_present():
    rows = extract_definitions(FIXTURES / "plain_script.py")
    qpaths = [r.qualified_path for r in rows]
    assert "process_records._validate" in qpaths


def test_plain_script_nested_function_kind():
    rows = extract_definitions(FIXTURES / "plain_script.py")
    row = _row(rows, "process_records._validate")
    assert row.kind == "nested_function"


def test_plain_script_nested_function_parent():
    rows = extract_definitions(FIXTURES / "plain_script.py")
    row = _row(rows, "process_records._validate")
    assert row.parent_path == "process_records"


def test_plain_script_lineno_start_end_reasonable():
    rows = extract_definitions(FIXTURES / "plain_script.py")
    row = _row(rows, "load_config")
    assert row.lineno_start >= 1
    assert row.lineno_end >= row.lineno_start


# ---------------------------------------------------------------------------
# extract_definitions — oop_script.py
# ---------------------------------------------------------------------------


def test_oop_script_class_row_present():
    rows = extract_definitions(FIXTURES / "oop_script.py")
    row = _row(rows, "DataProcessor")
    assert row.kind == "class"


def test_oop_script_methods_present():
    rows = extract_definitions(FIXTURES / "oop_script.py")
    qpaths = [r.qualified_path for r in rows]
    assert "DataProcessor.__init__" in qpaths
    assert "DataProcessor.run" in qpaths
    assert "DataProcessor._process_chunk" in qpaths
    assert "DataProcessor.validate" in qpaths


def test_oop_script_method_parent_path():
    rows = extract_definitions(FIXTURES / "oop_script.py")
    row = _row(rows, "DataProcessor.run")
    assert row.parent_path == "DataProcessor"


def test_oop_script_nested_func_inside_method():
    rows = extract_definitions(FIXTURES / "oop_script.py")
    qpaths = [r.qualified_path for r in rows]
    assert "DataProcessor.run._chunk" in qpaths


def test_oop_script_nested_func_kind():
    rows = extract_definitions(FIXTURES / "oop_script.py")
    row = _row(rows, "DataProcessor.run._chunk")
    assert row.kind == "nested_function"


def test_oop_script_decorator_captured():
    rows = extract_definitions(FIXTURES / "oop_script.py")
    row = _row(rows, "DataProcessor.validate")
    import json
    assert "staticmethod" in json.loads(row.decorators)


def test_oop_script_top_level_function_present():
    rows = extract_definitions(FIXTURES / "oop_script.py")
    qpaths = [r.qualified_path for r in rows]
    assert "bootstrap" in qpaths


# ---------------------------------------------------------------------------
# extract_definitions — mixed_script.py
# ---------------------------------------------------------------------------


def test_mixed_script_has_both_class_and_functions():
    rows = extract_definitions(FIXTURES / "mixed_script.py")
    qpaths = [r.qualified_path for r in rows]
    assert "ReportWriter" in qpaths
    assert "read_file" in qpaths
    assert "summarise" in qpaths


def test_mixed_script_class_method_and_nested():
    rows = extract_definitions(FIXTURES / "mixed_script.py")
    qpaths = [r.qualified_path for r in rows]
    assert "ReportWriter.write" in qpaths
    assert "ReportWriter.write._build_path" in qpaths
    assert "ReportWriter.supported" in qpaths


# ---------------------------------------------------------------------------
# Hash correctness
# ---------------------------------------------------------------------------


def test_combined_hash_is_sig_plus_body(tmp_path):
    f = tmp_path / "simple.py"
    f.write_text("def foo(x: int) -> int:\n    return x + 1\n")
    rows = extract_definitions(f)
    row = _row(rows, "foo")
    expected = _sha256(f"{row.signature_hash}:{row.body_hash}")
    assert row.combined_hash == expected


def test_body_hash_changes_on_docstring_change(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text('def foo():\n    """Original docstring."""\n    return 1\n')
    f2.write_text('def foo():\n    """Changed docstring."""\n    return 1\n')
    r1 = _row(extract_definitions(f1), "foo")
    r2 = _row(extract_definitions(f2), "foo")
    assert r1.body_hash != r2.body_hash


def test_signature_hash_changes_on_arg_rename(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo(x: int) -> int:\n    return x\n")
    f2.write_text("def foo(value: int) -> int:\n    return value\n")
    r1 = _row(extract_definitions(f1), "foo")
    r2 = _row(extract_definitions(f2), "foo")
    assert r1.signature_hash != r2.signature_hash


def test_signature_hash_stable_across_body_change(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo(x: int) -> int:\n    return x\n")
    f2.write_text("def foo(x: int) -> int:\n    return x * 2\n")
    r1 = _row(extract_definitions(f1), "foo")
    r2 = _row(extract_definitions(f2), "foo")
    assert r1.signature_hash == r2.signature_hash
    assert r1.body_hash != r2.body_hash


def test_class_body_hash_excludes_method_bodies(tmp_path):
    """Changing a method body should NOT change the class row's body_hash."""
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text(
        "class Foo:\n"
        "    x = 1\n"
        "    def bar(self):\n"
        "        return 1\n"
    )
    f2.write_text(
        "class Foo:\n"
        "    x = 1\n"
        "    def bar(self):\n"
        "        return 999\n"
    )
    r1 = _row(extract_definitions(f1), "Foo")
    r2 = _row(extract_definitions(f2), "Foo")
    assert r1.body_hash == r2.body_hash


def test_module_statements_row_absent_for_definitions_only(tmp_path):
    """A file with only function/class definitions and no module-level
    statements should have no <module_statements> row."""
    f = tmp_path / "defs_only.py"
    f.write_text(
        "def foo():\n    return 1\n\n"
        "def bar():\n    return 2\n"
    )
    rows = extract_definitions(f)
    qpaths = [r.qualified_path for r in rows]
    assert "<module_statements>" not in qpaths