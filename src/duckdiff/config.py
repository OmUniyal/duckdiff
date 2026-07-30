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

    enable_fuzzy_column_mapping: bool = False
    fuzzy_match_threshold: float = 0.6

    sanity_check_mode: bool = False

    # Bounded, in-memory preview of mismatched rows (see
    # results.MismatchSample), returned as part of ComparisonResult.
    # Requires key_columns for the same reason tolerances do -- "which
    # column differs for this row" needs an aligned row to compare
    # against, which only exists in keyed mode. For full, unbounded
    # mismatch/only-in detail, use ComparisonSession.export_mismatches()
    # instead of raising this number -- that path streams to disk rather
    # than holding everything in memory.
    include_mismatch_samples: bool = False
    mismatch_sample_size: int = 3

    chunk_size: int = 1_000_000