import argparse

import pytest

from duckdiff.cli import _build_tolerance_rules, _key_value_float, build_parser, main
from duckdiff.config import ToleranceRule


def _write_csv(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("\n".join(rows) + "\n")
    return str(path)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_parses_sources_and_repeatable_key():
    parser = build_parser()
    args = parser.parse_args(["a=a.csv", "b=b.csv", "--key", "id", "--key", "region"])
    assert args.sources == ["a=a.csv", "b=b.csv"]
    assert args.key_columns == ["id", "region"]


def test_ignore_is_repeatable():
    parser = build_parser()
    args = parser.parse_args(["a=a.csv", "b=b.csv", "--ignore", "updated_at", "--ignore", "note"])
    assert args.ignore_columns == ["updated_at", "note"]


def test_case_insensitive_and_sanity_check_flags_default_false():
    parser = build_parser()
    args = parser.parse_args(["a=a.csv", "b=b.csv"])
    assert args.case_insensitive is False
    assert args.sanity_check is False


def test_case_insensitive_and_sanity_check_flags_can_be_set():
    parser = build_parser()
    args = parser.parse_args(["a=a.csv", "b=b.csv", "--case-insensitive", "--sanity-check"])
    assert args.case_insensitive is True
    assert args.sanity_check is True


def test_tolerance_abs_and_rel_parse_into_tuples():
    parser = build_parser()
    args = parser.parse_args(
        ["a=a.csv", "b=b.csv", "--tolerance-abs", "amount=0.01", "--tolerance-rel", "qty=0.02"]
    )
    assert args.tolerance_abs == [("amount", 0.01)]
    assert args.tolerance_rel == [("qty", 0.02)]


def test_malformed_tolerance_spec_exits_with_usage_error():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["a=a.csv", "b=b.csv", "--tolerance-abs", "amount"])  # no '='
    assert exc_info.value.code == 2


def test_non_numeric_tolerance_value_exits_with_usage_error():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["a=a.csv", "b=b.csv", "--tolerance-abs", "amount=notanumber"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# _key_value_float
# ---------------------------------------------------------------------------


def test_key_value_float_parses_valid_spec():
    assert _key_value_float("amount=0.05") == ("amount", 0.05)


def test_key_value_float_rejects_missing_equals():
    with pytest.raises(argparse.ArgumentTypeError, match="COLUMN=VALUE"):
        _key_value_float("amount")


def test_key_value_float_rejects_non_numeric_value():
    with pytest.raises(argparse.ArgumentTypeError, match="not a valid number"):
        _key_value_float("amount=abc")


# ---------------------------------------------------------------------------
# _build_tolerance_rules
# ---------------------------------------------------------------------------


def test_build_tolerance_rules_merges_abs_and_rel_for_same_column():
    """A column with both --tolerance-abs and --tolerance-rel must land on
    ONE ToleranceRule with both fields set, not two separate rules."""
    rules = _build_tolerance_rules(abs_pairs=[("amount", 0.01)], rel_pairs=[("amount", 0.02)])
    assert rules == [ToleranceRule(column="amount", absolute=0.01, relative=0.02)]


def test_build_tolerance_rules_handles_disjoint_columns():
    rules = _build_tolerance_rules(abs_pairs=[("amount", 0.01)], rel_pairs=[("qty", 0.02)])
    assert ToleranceRule(column="amount", absolute=0.01) in rules
    assert ToleranceRule(column="qty", relative=0.02) in rules
    assert len(rules) == 2


# ---------------------------------------------------------------------------
# main() end-to-end
# ---------------------------------------------------------------------------


def test_main_reports_matched_and_mismatched(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "2,25.0"])
    exit_code = main([f"a={a}", f"b={b}", "--key", "id"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Matched:     1" in out
    assert "Mismatched:  1" in out


def test_main_applies_ignore_columns(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["id,amount,note", "1,10.0,x"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount,note", "1,10.0,y"])
    exit_code = main([f"a={a}", f"b={b}", "--key", "id", "--ignore", "note"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Matched:     1" in out
    assert "Mismatched:  0" in out


def test_main_applies_tolerance(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.00"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.04"])
    exit_code = main([f"a={a}", f"b={b}", "--key", "id", "--tolerance-abs", "amount=0.05"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Matched:     1" in out


def test_main_reports_schema_mismatch_as_friendly_error_not_traceback(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,total", "1,10.0"])
    exit_code = main([f"a={a}", f"b={b}"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error:")
    assert "Traceback" not in captured.err


def test_main_reports_config_error_as_friendly_error(tmp_path, capsys):
    """Tolerance without --key should surface as a clean Error: line, not a
    raw ConfigurationError traceback."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    exit_code = main([f"a={a}", f"b={b}", "--tolerance-abs", "amount=0.01"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error:")


def test_main_reports_missing_file_as_friendly_error_not_traceback(tmp_path, capsys):
    """Found via manual smoke testing: a nonexistent source file raised a raw
    duckdb.IOException traceback instead of our Error: line, since duckdb.Error
    isn't in DuckDiffError's hierarchy and wasn't originally caught."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    missing = str(tmp_path / "does_not_exist.csv")
    exit_code = main([f"a={a}", f"b={missing}"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error:")
    assert "Traceback" not in captured.err


def test_main_rejects_source_without_equals_sign(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    with pytest.raises(SystemExit) as exc_info:
        main([f"{a}", f"b={a}"])  # missing 'name=' on the first source
    assert exc_info.value.code == 2