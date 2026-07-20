"""CLI entry point for duckdiff, split into subcommands.

All comparison logic lives in ComparisonSession; this module only
handles argument parsing, dispatch, and output formatting, on purpose --
so the CLI can never drift from what the library does.

Subcommands:
  duckdiff compare ...   -- run a comparison from the command line
  duckdiff ui             -- launch the local web UI (not yet implemented)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

import duckdb

from duckdiff.config import ComparisonConfig, ToleranceRule
from duckdiff.exceptions import DuckDiffError, SchemaMismatchError
from duckdiff.results import ComparisonResult
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="duckdiff",
        description="N-way, order-independent comparison of large record files.",
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
        enable_fuzzy_column_mapping=args.fuzzy_map,
    )


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


def _run_ui(args: argparse.Namespace) -> int:
    print("duckdiff ui is not implemented yet -- coming in a future phase.", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None, input_func: Callable[[str], str] = input) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "compare":
        return _run_compare(parser, args, input_func)
    if args.command == "ui":
        return _run_ui(args)

    parser.error(f"unknown command '{args.command}'")  # unreachable: required=True guards this
    raise AssertionError("unreachable")  # appease mypy's return-type check


if __name__ == "__main__":
    sys.exit(main())