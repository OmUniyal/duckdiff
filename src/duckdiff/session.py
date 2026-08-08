"""ComparisonSession: the primary entry point for duckdiff.

The CLI (and any future UI) are thin wrappers around this class — all
real logic lives here so every surface behaves identically and there's
exactly one place to test.
"""

from __future__ import annotations

from typing import Any

import duckdb

from duckdiff.comparator import dry_run as _dry_run
from duckdiff.comparator import export_mismatches as _export_mismatches
from duckdiff.comparator import get_source_columns, run_comparison
from duckdiff.comparator import suggest_key_columns as _suggest_key_columns
from duckdiff.config import ComparisonConfig
from duckdiff.exceptions import ConfigurationError
from duckdiff.results import ComparisonResult, DryRunResult, KeyColumnSuggestion
from duckdiff.schema import suggest_column_mapping as _suggest_column_mapping


class ComparisonSession:
    """Orchestrates an N-way comparison across multiple record sources.

    Example
    -------
    >>> session = ComparisonSession()
    >>> session.add_source("legacy", "legacy_export.csv")
    >>> session.add_source("new", "new_export.parquet")
    >>> result = session.compare(key_columns=["record_id"])
    """

    def __init__(self, config: ComparisonConfig | None = None) -> None:
        self.config = config or ComparisonConfig()
        self._sources: dict[str, str] = {}
        self._column_mapping: dict[str, dict[str, str]] = {}
        self._connection: duckdb.DuckDBPyConnection = duckdb.connect(database=":memory:")

    def add_source(self, name: str, path: str) -> ComparisonSession:
        """Register a source file under a given name. Returns self for chaining."""
        if name in self._sources:
            raise ValueError(f"Source '{name}' already registered.")
        self._sources[name] = path
        return self

    def suggest_column_mapping(self) -> dict[str, dict[str, str]]:
        """Return fuzzy column-mapping suggestions across registered sources.

        This never mutates the session's configuration -- it reads each
        source's raw schema and delegates to schema.suggest_column_mapping.
        Review the suggestions and opt in explicitly via
        `apply_column_mapping` if you want to use them for the next
        `compare()` call.
        """
        if len(self._sources) < 2:
            raise ValueError("Need at least 2 sources to suggest a column mapping.")
        source_columns = get_source_columns(self._connection, self._sources)
        return _suggest_column_mapping(source_columns, threshold=self.config.fuzzy_match_threshold)

    def apply_column_mapping(self, mapping: dict[str, dict[str, str]]) -> ComparisonSession:
        """Explicitly accept a column mapping (own or suggested) for future compares.

        Requires `config.enable_fuzzy_column_mapping = True` first -- a
        second, deliberate opt-in on top of accepting a specific mapping,
        so a mapping can never get applied just by boilerplate/copy-pasted
        code running without the caller consciously turning the feature
        on.
        """
        if not self.config.enable_fuzzy_column_mapping:
            raise ConfigurationError(
                "apply_column_mapping() requires config.enable_fuzzy_column_mapping "
                "to be True. Set it explicitly before applying a mapping."
            )
        unknown_sources = set(mapping) - set(self._sources)
        if unknown_sources:
            raise ValueError(
                f"Column mapping references unknown source(s): {sorted(unknown_sources)}"
            )
        self._column_mapping = mapping
        return self

    def compare(self, key_columns: list[str] | None = None) -> ComparisonResult:
        """Run the comparison across all registered sources."""
        if len(self._sources) < 2:
            raise ValueError("Need at least 2 sources to compare.")
        if key_columns:
            self.config.key_columns = key_columns
        return run_comparison(
            self._sources,
            self.config,
            connection=self._connection,
            column_mapping=self._column_mapping or None,
        )

    def dry_run(self) -> DryRunResult:
        """Cheap pre-flight preview: schema introspection + file sizes only.

        No row data is scanned. Returns a DryRunResult describing what
        compare() would do -- including any schema error that would be
        raised -- without actually running the comparison.
        """
        if len(self._sources) < 2:
            raise ValueError("Need at least 2 sources to dry-run.")
        return _dry_run(
            self._sources,
            self.config,
            connection=self._connection,
            column_mapping=self._column_mapping or None,
        )

    def suggest_key_columns(self, source_name: str) -> list[KeyColumnSuggestion]:
        """Suggest which column(s) uniquely identify rows in a single registered source.

        Tests single columns first, then composites in increasing size, stopping
        at the first size that yields a unique key. Measure-like columns
        (revenue, quantity, etc.) are excluded from candidacy automatically.

        Returns a ranked list of KeyColumnSuggestion -- unique keys first.
        Non-unique candidates are included so you can see how close each
        combination gets if no perfect key is found.
        """
        if source_name not in self._sources:
            raise ValueError(
                f"Source '{source_name}' is not registered. "
                f"Available: {sorted(self._sources)}"
            )
        return _suggest_key_columns(
            self._sources[source_name],
            connection=self._connection,
        )

    def export_mismatches(self, output_path: str) -> None:
            """Write the full mismatch and only-in detail to disk.
            Requires config.key_columns."""
            if len(self._sources) < 2:
                raise ValueError("Need at least 2 sources to export mismatches.")
            _export_mismatches(
                self._sources,
                self.config,
                output_path,
                connection=self._connection,
                column_mapping=self._column_mapping or None,
            )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> ComparisonSession:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()