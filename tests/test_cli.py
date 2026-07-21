import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from duckdiff.cli import (
    _build_tolerance_rules,
    _key_value_float,
    _prompt_yes_no,
    build_parser,
    main,
)
from duckdiff.config import ToleranceRule


def _write_csv(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("\n".join(rows) + "\n")
    return str(path)


# ---------------------------------------------------------------------------
# Subcommand dispatch
# ---------------------------------------------------------------------------


def test_bare_command_with_no_subcommand_exits_with_usage_error():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([])
    assert exc_info.value.code == 2


def test_unknown_subcommand_exits_with_usage_error():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["frobnicate", "a=a.csv", "b=b.csv"])
    assert exc_info.value.code == 2


def test_ui_subcommand_parses_with_no_arguments():
    parser = build_parser()
    args = parser.parse_args(["ui"])
    assert args.command == "ui"


def test_ui_subcommand_launches_streamlit_with_the_app_path():
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, returncode=0)

    exit_code = main(["ui"], ui_runner=fake_runner)
    assert exit_code == 0
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "streamlit"]
    assert cmd[3] == "run"
    assert cmd[4].endswith(str(Path("ui") / "app.py"))


def test_ui_subcommand_suppresses_telemetry_prompt():
    """Streamlit's first-run flow asks for an email as part of its own
    telemetry opt-in -- someone running `duckdiff ui` shouldn't see a
    prompt that looks like it's coming from duckdiff itself.

    The prompt is specifically gated by server.showEmailPrompt --
    browser.gatherUsageStats alone does NOT skip the prompt, only
    whether stats get sent afterward, so both must be checked."""
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, returncode=0)

    main(["ui"], ui_runner=fake_runner)
    _, kwargs = calls[0]
    assert kwargs["env"]["STREAMLIT_SERVER_SHOW_EMAIL_PROMPT"] == "false"
    assert kwargs["env"]["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] == "false"


def test_ui_subcommand_propagates_streamlit_exit_code():
    exit_code = main(
        ["ui"], ui_runner=lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, returncode=3)
    )
    assert exit_code == 3


# ---------------------------------------------------------------------------
# Argument parsing (duckdiff compare)
# ---------------------------------------------------------------------------


def test_parses_sources_and_repeatable_key():
    parser = build_parser()
    args = parser.parse_args(["compare", "a=a.csv", "b=b.csv", "--key", "id", "--key", "region"])
    assert args.sources == ["a=a.csv", "b=b.csv"]
    assert args.key_columns == ["id", "region"]


def test_ignore_is_repeatable():
    parser = build_parser()
    args = parser.parse_args(
        ["compare", "a=a.csv", "b=b.csv", "--ignore", "updated_at", "--ignore", "note"]
    )
    assert args.ignore_columns == ["updated_at", "note"]


def test_case_insensitive_and_sanity_check_flags_default_false():
    parser = build_parser()
    args = parser.parse_args(["compare", "a=a.csv", "b=b.csv"])
    assert args.case_insensitive is False
    assert args.sanity_check is False


def test_case_insensitive_and_sanity_check_flags_can_be_set():
    parser = build_parser()
    args = parser.parse_args(
        ["compare", "a=a.csv", "b=b.csv", "--case-insensitive", "--sanity-check"]
    )
    assert args.case_insensitive is True
    assert args.sanity_check is True


def test_tolerance_abs_and_rel_parse_into_tuples():
    parser = build_parser()
    args = parser.parse_args(
        [
            "compare",
            "a=a.csv",
            "b=b.csv",
            "--tolerance-abs",
            "amount=0.01",
            "--tolerance-rel",
            "qty=0.02",
        ]
    )
    assert args.tolerance_abs == [("amount", 0.01)]
    assert args.tolerance_rel == [("qty", 0.02)]


def test_malformed_tolerance_spec_exits_with_usage_error():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["compare", "a=a.csv", "b=b.csv", "--tolerance-abs", "amount"])
    assert exc_info.value.code == 2


def test_non_numeric_tolerance_value_exits_with_usage_error():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["compare", "a=a.csv", "b=b.csv", "--tolerance-abs", "amount=notanumber"])
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
# main() end-to-end (duckdiff compare ...)
# ---------------------------------------------------------------------------


def test_main_reports_matched_and_mismatched(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0", "2,25.0"])
    exit_code = main(["compare", f"a={a}", f"b={b}", "--key", "id"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Matched:     1" in out
    assert "Mismatched:  1" in out


def test_main_applies_ignore_columns(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["id,amount,note", "1,10.0,x"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount,note", "1,10.0,y"])
    exit_code = main(["compare", f"a={a}", f"b={b}", "--key", "id", "--ignore", "note"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Matched:     1" in out
    assert "Mismatched:  0" in out


def test_main_applies_tolerance(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.00"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.04"])
    exit_code = main(
        ["compare", f"a={a}", f"b={b}", "--key", "id", "--tolerance-abs", "amount=0.05"]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Matched:     1" in out


def test_main_reports_schema_mismatch_as_friendly_error_not_traceback(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,total", "1,10.0"])
    exit_code = main(["compare", f"a={a}", f"b={b}"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error:")
    assert "Traceback" not in captured.err


def test_main_reports_config_error_as_friendly_error(tmp_path, capsys):
    """Tolerance without --key should surface as a clean Error: line, not a
    raw ConfigurationError traceback."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,amount", "1,10.0"])
    exit_code = main(["compare", f"a={a}", f"b={b}", "--tolerance-abs", "amount=0.01"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error:")


def test_main_reports_missing_file_as_friendly_error_not_traceback(tmp_path, capsys):
    """Found via manual smoke testing: a nonexistent source file raised a raw
    duckdb.IOException traceback instead of our Error: line, since duckdb.Error
    isn't in DuckDiffError's hierarchy and wasn't originally caught."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    missing = str(tmp_path / "does_not_exist.csv")
    exit_code = main(["compare", f"a={a}", f"b={missing}"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error:")
    assert "Traceback" not in captured.err


def test_main_rejects_source_without_equals_sign(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    with pytest.raises(SystemExit) as exc_info:
        main(["compare", f"{a}", f"b={a}"])  # missing 'name=' on the first source
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# _prompt_yes_no
# ---------------------------------------------------------------------------


def test_prompt_yes_no_accepts_y_and_yes():
    assert _prompt_yes_no("?", lambda _: "y") is True
    assert _prompt_yes_no("?", lambda _: "yes") is True
    assert _prompt_yes_no("?", lambda _: "Y") is True


def test_prompt_yes_no_rejects_anything_else():
    assert _prompt_yes_no("?", lambda _: "n") is False
    assert _prompt_yes_no("?", lambda _: "") is False
    assert _prompt_yes_no("?", lambda _: "sure") is False


def test_prompt_yes_no_declines_on_eof():
    def raise_eof(_):
        raise EOFError

    assert _prompt_yes_no("?", raise_eof) is False


# ---------------------------------------------------------------------------
# --fuzzy-map / --yes interactive retry flow
# ---------------------------------------------------------------------------


def test_fuzzy_map_without_flag_shows_original_error_only(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0"])
    exit_code = main(["compare", f"a={a}", f"b={b}"])  # no --fuzzy-map
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error:")
    assert "Suggested column mapping" not in captured.out


def test_fuzzy_map_shows_suggestion_and_accepts_on_y(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0", "2,20.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0", "2,25.0"])
    exit_code = main(
        ["compare", f"a={a}", f"b={b}", "--key", "customer_id", "--fuzzy-map"],
        input_func=lambda _: "y",
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Suggested column mapping:" in out
    assert "b.cust_id -> customer_id" in out
    assert "Matched:     1" in out
    assert "Mismatched:  1" in out


def test_fuzzy_map_declines_on_n(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0"])
    exit_code = main(
        ["compare", f"a={a}", f"b={b}", "--key", "customer_id", "--fuzzy-map"],
        input_func=lambda _: "n",
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Suggested column mapping:" in captured.out
    assert "Aborted" in captured.err


def test_fuzzy_map_yes_flag_skips_prompt_entirely(tmp_path, capsys):
    a = _write_csv(tmp_path, "a.csv", ["customer_id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["cust_id,amount", "1,10.0"])

    def explode(_):
        raise AssertionError("input_func should never be called when --yes is set")

    exit_code = main(
        ["compare", f"a={a}", f"b={b}", "--key", "customer_id", "--fuzzy-map", "--yes"],
        input_func=explode,
    )
    assert exit_code == 0


def test_fuzzy_map_with_no_suggestions_falls_back_to_original_error(tmp_path, capsys):
    """Columns different enough that suggest_column_mapping finds nothing --
    --fuzzy-map shouldn't pretend it can help."""
    a = _write_csv(tmp_path, "a.csv", ["id,amount", "1,10.0"])
    b = _write_csv(tmp_path, "b.csv", ["id,region", "1,us"])
    exit_code = main(
        ["compare", f"a={a}", f"b={b}", "--fuzzy-map"],
        input_func=lambda _: "y",
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error:")
    assert "No fuzzy column-mapping suggestions found" in captured.err