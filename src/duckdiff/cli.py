"""Thin CLI wrapper around ComparisonSession.

All comparison logic lives in ComparisonSession; this module only
handles argument parsing and output formatting, on purpose — so the
CLI can never drift from what the library does.
"""

from __future__ import annotations

import argparse
import sys

from duckdiff.session import ComparisonSession


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
        help="Key column to match rows on. Repeatable for composite keys.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    session = ComparisonSession()
    for pair in args.sources:
        if "=" not in pair:
            parser.error(f"Source '{pair}' must be in name=path format.")
        name, path = pair.split("=", 1)
        session.add_source(name, path)

    result = session.compare(key_columns=args.key_columns)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
