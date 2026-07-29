"""Result data structures returned by a ComparisonSession run."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceSummary:
    """Row/column counts and basic stats for a single input source."""

    name: str
    row_count: int
    column_count: int


@dataclass
class MismatchSample:
    """One mismatched row, for the bounded in-result sample (see
    ComparisonConfig.include_mismatch_samples). For the full, unbounded
    detail, use ComparisonSession.export_mismatches() instead -- this is
    only ever a small preview.

    `key` is the row's key-column values. `differences` is keyed by
    column name, each mapping to {source_name: value} for every source
    that column differs across -- only columns that actually differ for
    this key appear here, not every comparison column.
    """

    key: dict[str, object]
    differences: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass
class ComparisonResult:
    """The outcome of an N-way comparison run."""

    sources: list[SourceSummary] = field(default_factory=list)
    matched_row_count: int = 0
    mismatched_row_count: int = 0
    only_in: dict[str, int] = field(default_factory=dict)
    column_mapping: dict[str, dict[str, str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    mismatch_samples: list[MismatchSample] = field(default_factory=list)