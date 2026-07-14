"""Configuration objects for a comparison run.

Design principle: minimal-by-default. Every optional behavior (fuzzy
column mapping, tolerance-based matching, sanity-check mode) is opt-in
and must be explicitly enabled by the caller. Nothing here is ever
auto-applied to a comparison run without the caller asking for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToleranceRule:
    """A tolerance rule for approximate-equality comparison of a numeric column.

    At least one of `absolute` or `relative` should be set. If both are
    set, a value pair is considered equal if it passes either check.
    """

    column: str
    absolute: float | None = None
    relative: float | None = None  # e.g. 0.01 == within 1%


@dataclass
class ComparisonConfig:
    """Options controlling how a ComparisonSession runs.

    Every field defaults to the strictest, most minimal behavior: exact
    match on every column, no fuzzy column mapping, no tolerances, no
    sanity-check mode. Opt in to anything else explicitly.
    """

    key_columns: list[str] = field(default_factory=list)
    ignore_columns: list[str] = field(default_factory=list)
    tolerances: list[ToleranceRule] = field(default_factory=list)
    case_sensitive: bool = True

    # Fuzzy column-name matching across sources. Suggestions are always
    # surfaced for review via ComparisonSession.suggest_column_mapping();
    # this flag only controls whether compare() is willing to run at all
    # when schemas don't line up exactly, using an *explicitly accepted*
    # mapping — it never causes a mapping to be guessed and applied silently.
    enable_fuzzy_column_mapping: bool = False
    fuzzy_match_threshold: float = 0.6  # was 0.85 -- see schema.py docstring for why

    # Sanity-check mode: run cheap pre-flight checks (row counts, column
    # overlap, dtype compatibility) and report them before doing the full
    # comparison. Useful for catching obviously-wrong file pairs early.
    sanity_check_mode: bool = False

    # Streaming chunk size (rows) for out-of-core processing via DuckDB.
    chunk_size: int = 1_000_000
