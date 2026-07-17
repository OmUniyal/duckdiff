"""Thin CLI wrapper around ComparisonSession.

All comparison logic lives in ComparisonSession; this module only
handles argument parsing and output formatting, on purpose -- so the
CLI can never drift from what the library does.
"""

from __future__ import annotations

import argparse
import sys

import duckdb

from duckdiff.config import ComparisonConfig, ToleranceRule
from duckdiff.exceptions import DuckDiffError
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="duckdiff",
        description="N-way, order-independent comparison of large record files.",
    )
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    session = ComparisonSession(_build_config(args))
    for pair in args.sources:
        if "=" not in pair:
            parser.error(f"Source '{pair}' must be in name=path format.")
        name, path = pair.split("=", 1)
        session.add_source(name, path)

    try:
        result = session.compare()
    except (DuckDiffError, ValueError, duckdb.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(_format_result(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())