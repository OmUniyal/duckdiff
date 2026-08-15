"""CLI entry point for duckdiff, split into subcommands.

All comparison logic lives in ComparisonSession; this module only
handles argument parsing, dispatch, and output formatting, on purpose --
so the CLI can never drift from what the library does.

Subcommands:
  duckdiff compare ...   -- run a comparison from the command line
  duckdiff ui             -- launch the local web UI in your browser
  duckdiff keys ...       -- suggest key columns for a single source file
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import duckdb

from duckdiff import __version__
from duckdiff.config import ComparisonConfig, ToleranceRule
from duckdiff.exceptions import ConfigurationError, DuckDiffError, SchemaMismatchError
from duckdiff.python_file_session import PythonFileSession
from duckdiff.results import ComparisonResult, DryRunResult, PythonComparisonResult
from duckdiff.session import ComparisonSession


def _key_value_float(spec: str) -> tuple[str, float]:
    """argparse `type=` callable for COLUMN=VALUE tolerance arguments."""
    column, sep, value = spec.partition("=")
    if not sep or not column:
        raise argparse.ArgumentTypeError(f"expected COLUMN=VALUE, got '{spec}'")
    try:
        return column, float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid number") from exc


def _add_compare_arguments(parser: argparse.ArgumentParser) -> None:
    """Register every argument specific to `duckdiff compare`."""
    parser.add_argument(
        "sources",
        nargs="+",
        help="Source files to compare, as name=path pairs (e.g. old=a.csv new=b.csv).",
    )
    parser.add_argument(
        "--key",
        action="append",
        default=[],
        dest="key_columns",
        help="Key column to match rows on. Repeatable for composite keys. "
        "Omit for full-row (order-independent, duplicate-aware) comparison.",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        dest="ignore_columns",
        metavar="COLUMN",
        help="Column to exclude from comparison entirely. Repeatable.",
    )
    parser.add_argument(
        "--tolerance-abs",
        action="append",
        default=[],
        type=_key_value_float,
        dest="tolerance_abs",
        metavar="COLUMN=VALUE",
        help="Absolute tolerance for a numeric column (requires --key). Repeatable.",
    )
    parser.add_argument(
        "--tolerance-rel",
        action="append",
        default=[],
        type=_key_value_float,
        dest="tolerance_rel",
        metavar="COLUMN=VALUE",
        help="Relative tolerance (fraction, e.g. 0.01 = 1%%) for a numeric "
        "column (requires --key). Repeatable.",
    )
    parser.add_argument(
        "--case-insensitive",
        action="store_true",
        help="Compare string columns case-insensitively.",
    )
    parser.add_argument(
        "--sanity-check",
        action="store_true",
        dest="sanity_check",
        help="Surface cheap pre-flight warnings (row count disparity, etc).",
    )
    parser.add_argument(
        "--auto-intersect",
        action="store_true",
        dest="auto_intersect",
        help="Instead of failing on schema mismatches, compare only the columns "
        "present in all sources. Dropped columns are reported as warnings.",
    )
    parser.add_argument(
        "--fuzzy-map",
        action="store_true",
        dest="fuzzy_map",
        help="On a schema mismatch, suggest a column mapping and offer to "
        "apply it (with confirmation) instead of failing outright.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt and auto-accept a suggested "
        "mapping. Only relevant with --fuzzy-map.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Preview schema compatibility and file sizes without running the full comparison.",
    )


def _add_pyfile_subcommand(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the `duckdiff pyfile` subcommand."""
    pyfile_parser = subparsers.add_parser(
        "pyfile",
        help="Compare N Python source files via AST-based structural diff.",
        description="N-way, order-independent structural comparison of Python files.",
    )
    pyfile_parser.add_argument(
        "sources",
        nargs="+",
        help="Python files to compare, as name=path pairs (e.g. a=old.py b=new.py).",
    )
    pyfile_parser.add_argument(
        "--show-unchanged",
        action="store_true",
        dest="show_unchanged",
        help="Include unchanged definitions in the output (hidden by default).",
    )
    pyfile_parser.add_argument(
        "--no-nested",
        action="store_true",
        dest="no_nested",
        help="Suppress nested function rows from the output.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="duckdiff",
        description="N-way, order-independent comparison of large record files.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare N sources from the command line.",
        description="N-way, order-independent comparison of large record files.",
    )
    _add_compare_arguments(compare_parser)

    subparsers.add_parser(
        "ui",
        help="Launch the local web UI (not yet implemented).",
        description="Launch duckdiff's local web UI in a browser.",
    )

    _add_pyfile_subcommand(subparsers)

    keys_parser = subparsers.add_parser(
        "keys",
        help="Suggest key columns for a single source file.",
        description="Discover which column(s) uniquely identify rows in a file.",
    )
    keys_parser.add_argument(
        "source",
        help="Source file to inspect, as a name=path pair (e.g. a=data.csv).",
    )

    return parser


def _build_tolerance_rules(
    abs_pairs: list[tuple[str, float]],
    rel_pairs: list[tuple[str, float]],
) -> list[ToleranceRule]:
    """Merge --tolerance-abs and --tolerance-rel into one rule per column.

    A column can appear in both flags (an absolute AND a relative bound) --
    they need to land on the *same* ToleranceRule, not two separate ones.
    """
    rules: dict[str, ToleranceRule] = {}
    for column, value in abs_pairs:
        rules.setdefault(column, ToleranceRule(column=column)).absolute = value
    for column, value in rel_pairs:
        rules.setdefault(column, ToleranceRule(column=column)).relative = value
    return list(rules.values())


def _build_config(args: argparse.Namespace) -> ComparisonConfig:
    return ComparisonConfig(
        key_columns=args.key_columns,
        ignore_columns=args.ignore_columns,
        tolerances=_build_tolerance_rules(args.tolerance_abs, args.tolerance_rel),
        case_sensitive=not args.case_insensitive,
        sanity_check_mode=args.sanity_check,
        auto_intersect_columns=args.auto_intersect,
        enable_fuzzy_column_mapping=args.fuzzy_map,
    )


def _format_dry_run_result(result: DryRunResult) -> str:
    lines = ["Dry-run preview (no rows scanned):"]
    lines.append("")
    lines.append("Sources:")
    for source in result.sources:
        size_kb = source.file_size_bytes / 1024
        col_count = len(source.columns)
        lines.append(f"  {source.name}: {size_kb:,.1f} KB, {col_count} columns")
        lines.append(f"    columns: {', '.join(source.columns)}")

    if result.would_raise:
        lines.append("")
        lines.append(f"Schema error (compare would fail): {result.would_raise}")
    else:
        lines.append("")
        lines.append(f"Comparison columns ({len(result.comparison_columns)}): "
                     f"{', '.join(result.comparison_columns)}")

    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in result.warnings:
            lines.append(f"  - {warning}")

    return "\n".join(lines)


def _format_result(result: ComparisonResult) -> str:
    lines = ["Sources:"]
    for source in result.sources:
        lines.append(f"  {source.name}: {source.row_count:,} rows, {source.column_count} columns")

    lines.append("")
    lines.append(f"Matched:     {result.matched_row_count:,}")
    lines.append(f"Mismatched:  {result.mismatched_row_count:,}")
    for name, count in result.only_in.items():
        lines.append(f"Only in {name}: {count:,}")

    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in result.warnings:
            lines.append(f"  - {warning}")

    return "\n".join(lines)


def _prompt_yes_no(prompt: str, input_func: Callable[[str], str]) -> bool:
    try:
        answer = input_func(prompt)
    except EOFError:
        # Piped/closed stdin with no answer available -- decline, don't hang
        # or crash. Declining is the safe default: nothing gets applied.
        return False
    return answer.strip().lower() in ("y", "yes")


def _retry_with_fuzzy_mapping(
    session: ComparisonSession,
    original_error: SchemaMismatchError,
    args: argparse.Namespace,
    input_func: Callable[[str], str],
) -> ComparisonResult | None:
    """Handle a SchemaMismatchError by offering a fuzzy mapping, if enabled.

    Returns the comparison result on success, or None if the caller should
    treat this as a failure (already printed to stderr).
    """
    if not args.fuzzy_map:
        print(f"Error: {original_error}", file=sys.stderr)
        return None

    suggestion = session.suggest_column_mapping()
    if not suggestion:
        print(f"Error: {original_error}", file=sys.stderr)
        print("(No fuzzy column-mapping suggestions found.)", file=sys.stderr)
        return None

    print("Suggested column mapping:")
    for source, columns in suggestion.items():
        for original, canonical in columns.items():
            print(f"  {source}.{original} -> {canonical}")

    if not args.yes and not _prompt_yes_no("Apply this mapping and retry? [y/N] ", input_func):
        print("Aborted -- mapping not applied.", file=sys.stderr)
        return None

    session.apply_column_mapping(suggestion)
    try:
        return session.compare()
    except (DuckDiffError, ValueError, duckdb.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return None


def _run_compare(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    input_func: Callable[[str], str],
) -> int:
    session = ComparisonSession(_build_config(args))
    for pair in args.sources:
        if "=" not in pair:
            parser.error(f"Source '{pair}' must be in name=path format.")
        name, path = pair.split("=", 1)
        session.add_source(name, path)
    
    if args.dry_run:
        print(_format_dry_run_result(session.dry_run()))
        return 0

    try:
        result = session.compare()
    except SchemaMismatchError as exc:
        retried = _retry_with_fuzzy_mapping(session, exc, args, input_func)
        if retried is None:
            return 1
        result = retried
    except (DuckDiffError, ValueError, duckdb.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(_format_result(result))
    return 0


def _run_keys(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> int:
    from duckdiff.comparator import suggest_key_columns as _suggest_key_columns_gen

    pair = args.source
    if "=" not in pair:
        parser.error(f"Source '{pair}' must be in name=path format.")
    name, path = pair.split("=", 1)

    print(f"Key column suggestions for '{name}':")
    print()

    unique: list = []
    non_unique: list = []

    try:
        for suggestion in _suggest_key_columns_gen(path):
            label = " + ".join(suggestion.columns)
            if suggestion.is_unique:
                unique.append(suggestion)
                print(f"  ✓  {label}  (unique)")
            else:
                non_unique.append(suggestion)
                pct = suggestion.distinct_count / suggestion.total_count * 100
                print(
                    f"  -  {label:<40} "
                    f"{suggestion.distinct_count:,} distinct / "
                    f"{suggestion.total_count:,} rows ({pct:.1f}%)"
                )
    except (DuckDiffError, ValueError, duckdb.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if unique:
        print()
        flags = " ".join(f'--key "{c}"' for c in unique[0].columns)
        print(f"  Suggested: duckdiff compare ... {flags}")
    elif not non_unique:
        print("  No candidate keys found.")

    return 0


def _run_ui(
    args: argparse.Namespace,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> int:
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(
            "Error: the UI requires the 'ui' extra. Install with: pip install 'duckdiff[ui]'",
            file=sys.stderr,
        )
        return 1

    app_path = Path(__file__).parent / "ui" / "app.py"
        # Suppress Streamlit's first-run email prompt. This is gated by
        # server.showEmailPrompt specifically -- browser.gatherUsageStats
        # alone does NOT skip the prompt, only whether stats get sent
        # afterward. We deliberately don't use server.headless to suppress
        # it instead, since headless mode also disables Streamlit's
        # automatic browser-opening, which is the whole point of `duckdiff
        # ui`. (Confirmed empirically: server.headless was masking this bug
        # in earlier testing, since it happens to suppress the prompt for
        # an unrelated reason.)
    env = {
        **os.environ,
        "STREAMLIT_SERVER_SHOW_EMAIL_PROMPT": "false",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    }
    result = runner([sys.executable, "-m", "streamlit", "run", str(app_path)], env=env)
    return result.returncode


def _format_pyfile_result(
    result: PythonComparisonResult,
    show_unchanged: bool = False,
    no_nested: bool = False,
) -> str:
    NESTED_KINDS = {"nested_function"}
    SEP = "─" * 40

    if result.files_identical:
        return "✓  All files are structurally identical."

    if result.order_only:
        lines = [
            "⚠  Definition order differs — all definitions are semantically identical.",
            "   Order changes can affect runtime behaviour in scripts with module-level",
            "   execution or certain metaclass patterns.",
            "",
            "  Sources:",
        ]
        for label, path in result.sources.items():
            lines.append(f"    {label} = {path}")
        return "\n".join(lines)

    # ── Header ────────────────────────────────────────────────────────
    lines: list[str] = [
        f"Python file comparison: {len(result.sources)} source(s)",
        "",
        "  Sources:",
    ]
    for label, path in result.sources.items():
        lines.append(f"    {label} = {path}")

    lines.append("")
    summary_parts = []
    if result.changed:
        summary_parts.append(f"{result.changed} changed")
    if result.missing:
        summary_parts.append(f"{result.missing} missing")
    if result.unchanged:
        summary_parts.append(f"{result.unchanged} unchanged")
    lines.append(f"  Summary: {', '.join(summary_parts)}")

    # ── Filter helpers ─────────────────────────────────────────────────
    def _should_show(d: object) -> bool:
        from duckdiff.results import DefinitionDiff
        assert isinstance(d, DefinitionDiff)
        if no_nested and d.kind in NESTED_KINDS:
            return False
        return True

    def _display_path(qpath: str) -> str:
        return "[module level]" if qpath == "<module_statements>" else qpath

    def _change_detail(d: object) -> str:
        from duckdiff.results import DefinitionDiff
        assert isinstance(d, DefinitionDiff)
        if d.status != "changed":
            return ""
        if d.signature_changed and d.body_changed:
            return "  signature + body changed"
        if d.signature_changed:
            return "  signature changed"
        if d.body_changed:
            return "  body changed"
        return ""

    def _indent(qpath: str) -> str:
        """Indent nested definitions (those with a dot in qualified path)."""
        depth = qpath.count(".")
        return "    " * depth

    # ── CHANGED block ──────────────────────────────────────────────────
    changed_defs = [d for d in result.definitions if d.status == "changed" and _should_show(d)]
    if changed_defs:
        lines.append("")
        lines.append(SEP)
        lines.append("CHANGED")
        lines.append(SEP)
        for d in changed_defs:
            indent = _indent(d.qualified_path)
            detail = _change_detail(d)
            lines.append(
                f"  {indent}~ {_display_path(d.qualified_path):<45}"
                f"[lines {d.lineno_start}-{d.lineno_end}]{detail}"
            )

    # ── MISSING block ──────────────────────────────────────────────────
    missing_defs = [d for d in result.definitions if d.status == "missing" and _should_show(d)]
    if missing_defs:
        lines.append("")
        lines.append(SEP)
        lines.append("MISSING  (present in some sources only)")
        lines.append(SEP)
        for d in missing_defs:
            indent = _indent(d.qualified_path)
            lines.append(
                f"  {indent}? {_display_path(d.qualified_path):<45}"
                f"[lines {d.lineno_start}-{d.lineno_end}]"
                f"  present in: {d.present_in}"
            )

    # ── UNCHANGED block ────────────────────────────────────────────────
    unchanged_defs = [
        d for d in result.definitions if d.status == "unchanged" and _should_show(d)
    ]
    lines.append("")
    lines.append(SEP)
    if show_unchanged and unchanged_defs:
        lines.append("UNCHANGED")
        lines.append(SEP)
        for d in unchanged_defs:
            indent = _indent(d.qualified_path)
            lines.append(
                f"  {indent}= {_display_path(d.qualified_path):<45}"
                f"[lines {d.lineno_start}-{d.lineno_end}]"
            )
    else:
        lines.append("UNCHANGED")
        lines.append(SEP)
        if unchanged_defs:
            lines.append(
                f"  {len(unchanged_defs)} definition(s) identical across all sources."
                "  (--show-unchanged to display)"
            )
        else:
            lines.append("  (none)")

    return "\n".join(lines)


def _run_pyfile(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> int:
    session = PythonFileSession()
    for pair in args.sources:
        if "=" not in pair:
            parser.error(f"Source '{pair}' must be in name=path format.")
        name, path = pair.split("=", 1)
        try:
            session.add_source(name, path)
        except (DuckDiffError, ConfigurationError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

    try:
        result = session.compare()
    except (DuckDiffError, ConfigurationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(_format_pyfile_result(result, args.show_unchanged, args.no_nested))
    return 0 if (result.files_identical or result.order_only) else 1


def main(
    argv: list[str] | None = None,
    input_func: Callable[[str], str] = input,
    ui_runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "compare":
        return _run_compare(parser, args, input_func)
    if args.command == "ui":
        return _run_ui(args, ui_runner)
    if args.command == "keys":
        return _run_keys(parser, args)
    if args.command == "pyfile":
        return _run_pyfile(parser, args)

    parser.error(f"unknown command '{args.command}'")  # unreachable: required=True guards this
    raise AssertionError("unreachable")  # appease mypy's return-type check


if __name__ == "__main__":
    sys.exit(main())