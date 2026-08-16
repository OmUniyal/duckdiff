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

@dataclass
class SourcePreview:
    """Metadata for a single source in a dry-run preview.

    No row data is read -- file_size_bytes comes from the OS and
    columns comes from DuckDB's schema introspection (DESCRIBE).
    """

    name: str
    path: str
    file_size_bytes: int
    columns: list[str]

@dataclass
class DryRunResult:
    """The outcome of a dry_run() call.

    Always returned (never raises), so the caller can inspect what
    *would* happen before committing to a full comparison run.

    If the sources are schema-incompatible and auto_intersect_columns
    is False, `would_raise` holds the error message that compare()
    would have raised -- comparison_columns will be empty in that case.
    """

    sources: list[SourcePreview] = field(default_factory=list)
    comparison_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    would_raise: str | None = None

@dataclass
class KeyColumnSuggestion:
    """A candidate key combination found by suggest_key_columns().

    Returned as part of a ranked list -- unique keys (is_unique=True)
    bubble to the top. Non-unique candidates are included so the caller
    can see how close a combination gets to uniqueness even if no perfect
    key is found.
    """

    columns: list[str]
    distinct_count: int
    total_count: int
    is_unique: bool

# ---------------------------------------------------------------------------
# Python file comparison results (v0.2.0)
# ---------------------------------------------------------------------------


@dataclass
class DefinitionDiff:
    """Diff result for a single named definition across N Python files."""

    qualified_path: str    # e.g. "MyClass.my_method", "top_level_func"
    parent_path: str       # "" for top-level, "MyClass" for methods
    kind: str              # "function" | "async_function" | "class" | "nested_function" | "module_statements"
    status: str            # "changed" | "unchanged" | "missing"
    lineno_start: int      # from the file(s) where it exists
    lineno_end: int
    decorators: str        # JSON-serialised list of decorator name strings
    # populated only when status == "changed":
    signature_changed: bool = False
    body_changed: bool = False
    # populated only when status == "missing":
    present_in: str = ""   # comma-separated labels where definition exists
    # populated only when status == "renamed":
    renamed_from: str = ""  # original qualified_path before rename


@dataclass
class PythonComparisonResult:
    """Top-level result returned by PythonFileSession.compare()."""

    sources: dict[str, str]            # label → path
    files_identical: bool              # True = all file_hashes match, no drill-down needed
    file_hashes: dict[str, str]        # label → sha256 hash
    definitions: list[DefinitionDiff]  # empty when files_identical=True
    added: int = 0        # kept for potential future use (currently always 0 — see "missing")
    removed: int = 0      # kept for potential future use (currently always 0 — see "missing")
    changed: int = 0
    unchanged: int = 0
    missing: int = 0      # definitions present in some sources but not all
    renamed: int = 0      # definitions detected as renames via fuzzy path matching
    order_only: bool = False  # True when files differ in order only — all definitions unchanged