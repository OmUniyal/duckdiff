"""Core N-way comparison engine, powered by DuckDB.

Sources are streamed through DuckDB rather than loaded fully into
memory, so comparisons can scale past what fits in RAM. Row identity
across sources is established via an order-independent content hash
over the key columns (or the full row, if no keys are configured).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from duckdiff.config import ComparisonConfig
from duckdiff.results import ComparisonResult

if TYPE_CHECKING:
    import duckdb


def run_comparison(
    sources: dict[str, str],
    config: ComparisonConfig,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> ComparisonResult:
    """Run an N-way comparison across the given sources.

    Parameters
    ----------
    sources:
        Mapping of source name -> file path (CSV/Parquet/etc). DuckDB's
        native readers handle format detection.
    config:
        A ComparisonConfig controlling comparison behavior.
    connection:
        Optional existing DuckDB connection to reuse (e.g. an in-memory
        one shared across a longer-lived ComparisonSession) instead of
        opening a new one.
    """
    raise NotImplementedError("Comparison engine lands in the next phase.")
