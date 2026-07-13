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
class ComparisonResult:
    """The outcome of an N-way comparison run.

    `only_in` and `column_mapping` are keyed by source name so results
    stay legible for N > 2 sources, not just the pairwise case.
    """

    sources: list[SourceSummary] = field(default_factory=list)
    matched_row_count: int = 0
    mismatched_row_count: int = 0
    only_in: dict[str, int] = field(default_factory=dict)
    column_mapping: dict[str, dict[str, str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
