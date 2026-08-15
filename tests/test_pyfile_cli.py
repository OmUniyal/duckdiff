"""Tests for the `duckdiff pyfile` CLI subcommand (v0.2.0 Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from duckdiff.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(*args: str) -> tuple[int, str]:
    """Run main() with the given argv, capture stdout via capsys manually."""
    return main(list(args))


def run(capsys, *args: str) -> tuple[int, str]:
    code = main(list(args))
    out = capsys.readouterr().out
    return code, out


# ---------------------------------------------------------------------------
# Validation / error cases
# ---------------------------------------------------------------------------


def test_fewer_than_two_sources_exits_2(capsys):
    code, _ = run(capsys, "pyfile", f"a={FIXTURES / 'plain_script.py'}")
    assert code == 2


def test_nonexistent_file_exits_2(capsys):
    code, _ = run(
        capsys,
        "pyfile",
        "a=/nonexistent/foo.py",
        f"b={FIXTURES / 'plain_script.py'}",
    )
    assert code == 2


def test_non_py_file_exits_2(capsys, tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("a,b\n1,2\n")
    code, _ = run(
        capsys,
        "pyfile",
        f"a={f}",
        f"b={FIXTURES / 'plain_script.py'}",
    )
    assert code == 2


def test_missing_equals_in_source(capsys):
    """Source without '=' should trigger parser.error (SystemExit 2)."""
    with pytest.raises(SystemExit) as exc_info:
        main(["pyfile", "plain_script.py", f"b={FIXTURES / 'oop_script.py'}"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Identical files → exit 0
# ---------------------------------------------------------------------------


def test_identical_files_exit_0(capsys):
    code, out = run(
        capsys,
        "pyfile",
        f"a={FIXTURES / 'plain_script.py'}",
        f"b={FIXTURES / 'plain_script.py'}",
    )
    assert code == 0
    assert "structurally identical" in out


# ---------------------------------------------------------------------------
# Different files → exit 1
# ---------------------------------------------------------------------------


def test_different_files_exit_1(capsys):
    code, out = run(
        capsys,
        "pyfile",
        f"a={FIXTURES / 'plain_script.py'}",
        f"b={FIXTURES / 'oop_script.py'}",
    )
    assert code == 1
    assert "Summary:" in out


def test_changed_body_in_output(capsys, tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n")
    f2.write_text("def foo():\n    return 2\n")
    code, out = run(capsys, "pyfile", f"a={f1}", f"b={f2}")
    assert code == 1
    assert "body changed" in out
    assert "foo" in out


def test_changed_signature_in_output(capsys, tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    # Only the return annotation changes — body is identical
    f1.write_text("def foo(x: int) -> int:\n    return 1\n")
    f2.write_text("def foo(x: int) -> str:\n    return 1\n")
    code, out = run(capsys, "pyfile", f"a={f1}", f"b={f2}")
    assert code == 1
    assert "signature changed" in out


def test_missing_definition_in_output(capsys, tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
    f2.write_text("def foo():\n    return 1\n")
    code, out = run(capsys, "pyfile", f"a={f1}", f"b={f2}")
    assert code == 1
    assert "present in:" in out
    assert "bar" in out


# ---------------------------------------------------------------------------
# order_only → exit 0
# ---------------------------------------------------------------------------


def test_order_only_exit_0(capsys, tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
    f2.write_text("def bar():\n    return 2\n\ndef foo():\n    return 1\n")
    code, out = run(capsys, "pyfile", f"a={f1}", f"b={f2}")
    assert code == 0
    assert "order" in out.lower()


# ---------------------------------------------------------------------------
# --show-unchanged flag
# ---------------------------------------------------------------------------


def test_show_unchanged_flag(capsys, tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text(
        "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
    )
    f2.write_text(
        "def foo():\n    return 1\n\ndef bar():\n    return 99\n"
    )
    _, out_default = run(capsys, "pyfile", f"a={f1}", f"b={f2}")
    _, out_show = run(capsys, "pyfile", "--show-unchanged", f"a={f1}", f"b={f2}")
    # foo is unchanged — should appear only with --show-unchanged
    assert "= foo" not in out_default
    assert "= foo" in out_show


# ---------------------------------------------------------------------------
# --no-nested flag
# ---------------------------------------------------------------------------


def test_no_nested_flag_suppresses_nested(capsys, tmp_path):
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
    _, out_default = run(capsys, "pyfile", f"a={f1}", f"b={f2}")
    _, out_no_nested = run(capsys, "pyfile", "--no-nested", f"a={f1}", f"b={f2}")
    assert "inner" in out_default
    assert "inner" not in out_no_nested


# ---------------------------------------------------------------------------
# module_statements displays as [module level]
# ---------------------------------------------------------------------------


def test_module_statements_display(capsys, tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("X = 1\n\ndef foo():\n    return 1\n")
    f2.write_text("X = 99\n\ndef foo():\n    return 1\n")
    _, out = run(capsys, "pyfile", f"a={f1}", f"b={f2}")
    assert "[module level]" in out
    assert "<module_statements>" not in out