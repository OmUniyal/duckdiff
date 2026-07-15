"""Core N-way comparison engine, powered by DuckDB.

Sources are streamed through DuckDB rather than loaded fully into
memory, so comparisons can scale past what fits in RAM.

Two matching modes, chosen by whether `config.key_columns` is set:

- **No key columns** -- a row's entire content is its identity. This is
  a true order-independent, duplicate-aware (multiset/bag) comparison,
  implemented via DuckDB's native `INTERSECT ALL` / `EXCEPT ALL`, which
  are hash-based under the hood but avoid any hand-rolled-hash collision
  risk. There's no notion of a "mismatched" row here -- a row either is
  or isn't part of the common content.
- **Key columns given** -- rows are aligned across sources by key (via a
  chained `FULL OUTER JOIN ... USING`), then the remaining columns are
  diffed per aligned row, honoring tolerance rules. This is what lets
  results distinguish "row X differs in column Y" from "row X is only
  in source A".

Tolerance rules only make sense in keyed mode -- approximate equality
needs two specific, aligned values to compare. `run_comparison` raises
`ConfigurationError` if tolerances are set without key columns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from duckdiff.config import ComparisonConfig, ToleranceRule
from duckdiff.exceptions import ConfigurationError, SchemaMismatchError
from duckdiff.results import ComparisonResult, SourceSummary

if TYPE_CHECKING:
    import duckdb

_READERS = {".csv", ".tsv", ".parquet"}


def _extension(path: str) -> str:
    filename = path.rsplit("/", 1)[-1]
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def _reader_sql(path: str) -> str:
    """Return a DuckDB table-function call that reads `path`, based on its extension."""
    ext = _extension(path)
    escaped = path.replace("'", "''")
    if ext == ".parquet":
        return f"read_parquet('{escaped}')"
    if ext == ".csv":
        return f"read_csv_auto('{escaped}')"
    if ext == ".tsv":
        return f"read_csv_auto('{escaped}', delim='\\t')"
    supported = ", ".join(sorted(_READERS))
    raise ConfigurationError(
        f"Unsupported file extension '{ext}' for '{path}'. Supported: {supported}"
    )


def _q(identifier: str) -> str:
    """Quote a SQL identifier."""
    return '"' + identifier.replace('"', '""') + '"'


def _fetch_row(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[object, ...]:
    """Run a query expected to return exactly one row, and return it.

    A COUNT(*)/SUM(...) query always returns a row (possibly with NULLs),
    never zero rows -- if this assertion ever fires, something upstream
    built a malformed query, not a "no results" situation to handle
    gracefully.
    """
    row = con.execute(sql).fetchone()
    assert row is not None, f"Expected exactly one row, got none, for query: {sql}"
    return row


def _scalar_query(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    """Run a query expected to return a single count in its first column."""
    value = _fetch_row(con, sql)[0]
    assert isinstance(value, int)
    return value


def _sum_as_int(value: object) -> int:
    """Narrow a SUM(...) result to int, treating SQL NULL (empty group) as 0."""
    if value is None:
        return 0
    assert isinstance(value, int)
    return value


def _register_source(
    con: duckdb.DuckDBPyConnection,
    alias: str,
    path: str,
    column_mapping: dict[str, str] | None = None,
) -> list[str]:
    """Create a view over `path` named `alias` and return its column names.

    If `column_mapping` (original_name -> canonical_name) is given, the
    view's columns are renamed accordingly -- unmapped columns keep their
    original name. This is the only place renaming happens: everything
    downstream (schema validation, comparison SQL) just sees whatever
    column names come back from this function, mapped or not.
    """
    reader = _reader_sql(path)
    if column_mapping:
        raw_columns = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {reader}").fetchall()]
        select_list = ", ".join(
            f"{_q(col)} AS {_q(column_mapping.get(col, col))}" for col in raw_columns
        )
        con.execute(f"CREATE OR REPLACE VIEW {_q(alias)} AS SELECT {select_list} FROM {reader}")
    else:
        con.execute(f"CREATE OR REPLACE VIEW {_q(alias)} AS SELECT * FROM {reader}")
    return [row[0] for row in con.execute(f"DESCRIBE {_q(alias)}").fetchall()]


def get_source_columns(
    con: duckdb.DuckDBPyConnection,
    sources: dict[str, str],
    column_mapping: dict[str, dict[str, str]] | None = None,
) -> dict[str, list[str]]:
    """Register every source as a view on `con` and return its column names.

    Shared by `run_comparison` (registering for a real comparison, with
    an accepted mapping if one exists) and
    `ComparisonSession.suggest_column_mapping` (registering to read raw
    schemas -- no mapping, since that's what we're trying to compute).
    """
    return {
        alias: _register_source(con, alias, path, (column_mapping or {}).get(alias))
        for alias, path in sources.items()
    }


def _comparison_columns(
    source_columns: dict[str, list[str]],
    ignore_columns: list[str],
) -> list[str]:
    """Determine the columns to compare, validating that schemas line up.

    Requires an exact column-name match across all sources (order doesn't
    matter) once ignored columns are removed. Reconciling mismatched
    column *names* across sources is fuzzy-mapping's job, not this one's.
    """
    ignore = set(ignore_columns)
    column_sets = {name: set(cols) - ignore for name, cols in source_columns.items()}
    reference_name, reference_set = next(iter(column_sets.items()))
    for name, cols in column_sets.items():
        if cols != reference_set:
            missing = reference_set - cols
            extra = cols - reference_set
            raise SchemaMismatchError(
                f"Source '{name}' schema doesn't match source '{reference_name}' "
                f"after applying ignore_columns. Missing here: {sorted(missing)}. "
                f"Extra here: {sorted(extra)}. Use column mapping to reconcile "
                f"mismatched names, or add them to ignore_columns."
            )
    reference_cols = source_columns[reference_name]
    return [c for c in reference_cols if c in reference_set]


def _validate_config(config: ComparisonConfig, comparison_columns: list[str]) -> None:
    if config.tolerances and not config.key_columns:
        raise ConfigurationError(
            "Tolerance rules require key_columns -- approximate equality needs "
            "two aligned rows to compare specific values against. Set "
            "key_columns, or drop the tolerance rules for a full-row "
            "content comparison."
        )
    comparison_set = set(comparison_columns)
    unknown_tolerance_cols = {t.column for t in config.tolerances} - comparison_set
    if unknown_tolerance_cols:
        raise ConfigurationError(
            f"Tolerance rule(s) reference unknown column(s): {sorted(unknown_tolerance_cols)}"
        )
    unknown_keys = set(config.key_columns) - comparison_set
    if unknown_keys:
        raise ConfigurationError(f"key_columns reference unknown column(s): {sorted(unknown_keys)}")


def _tolerance_predicate(rule: ToleranceRule, left: str, right: str) -> str:
    """Boolean SQL expression for approximate equality of two non-null numeric columns."""
    checks = []
    if rule.absolute is not None:
        checks.append(f"ABS({left} - {right}) <= {rule.absolute}")
    if rule.relative is not None:
        checks.append(
            f"(({left} = 0 AND {right} = 0) OR "
            f"(ABS({left} - {right}) / NULLIF(ABS({right}), 0)) <= {rule.relative})"
        )
    if not checks:
        return f"{left} = {right}"
    return "(" + " OR ".join(checks) + ")"


def _column_equality_sql(
    column: str,
    left: str,
    right: str,
    config: ComparisonConfig,
    tolerance_by_column: dict[str, ToleranceRule],
) -> str:
    """Null-safe equality expression for one column, honoring tolerance/case-sensitivity."""
    if column in tolerance_by_column:
        approx = _tolerance_predicate(tolerance_by_column[column], left, right)
        return (
            f"(({left} IS NULL AND {right} IS NULL) OR "
            f"({left} IS NOT NULL AND {right} IS NOT NULL AND {approx}))"
        )
    if config.case_sensitive:
        return f"{left} IS NOT DISTINCT FROM {right}"
    return f"LOWER({left}::VARCHAR) IS NOT DISTINCT FROM LOWER({right}::VARCHAR)"


def _mode_full_row(
    con: duckdb.DuckDBPyConnection,
    aliases: list[str],
    comparison_columns: list[str],
) -> tuple[int, dict[str, int]]:
    """Full-row multiset comparison: a row's entire content is its identity."""
    col_list = ", ".join(_q(c) for c in comparison_columns)
    selects = {alias: f"SELECT {col_list} FROM {_q(alias)}" for alias in aliases}
    intersection_sql = " INTERSECT ALL ".join(selects.values())

    con.execute(f"CREATE OR REPLACE TEMP TABLE __full_intersection__ AS {intersection_sql}")
    matched_row_count = _scalar_query(con, "SELECT COUNT(*) FROM __full_intersection__")

    only_in: dict[str, int] = {}
    for alias, select_sql in selects.items():
        only_sql = f"({select_sql}) EXCEPT ALL (SELECT * FROM __full_intersection__)"
        only_in[alias] = _scalar_query(con, f"SELECT COUNT(*) FROM ({only_sql})")

    con.execute("DROP TABLE __full_intersection__")
    return matched_row_count, only_in


def _mode_keyed(
    con: duckdb.DuckDBPyConnection,
    aliases: list[str],
    comparison_columns: list[str],
    config: ComparisonConfig,
) -> tuple[int, int, dict[str, int]]:
    """Key-aligned comparison: rows are matched by key, then diffed column-by-column."""
    key_columns = config.key_columns
    value_columns = [c for c in comparison_columns if c not in key_columns]
    tolerance_by_column = {t.column: t for t in config.tolerances}
    key_using = ", ".join(_q(k) for k in key_columns)
    first_key = _q(key_columns[0])

    select_parts: list[str] = []
    for alias in aliases:
        cols = [f"({_q(alias)}.{first_key} IS NOT NULL) AS {_q('__present_' + alias)}"]
        cols += [f"{_q(alias)}.{_q(col)} AS {_q(alias + '__' + col)}" for col in value_columns]
        select_parts.append(", ".join(cols))

    join_clause = _q(aliases[0])
    for alias in aliases[1:]:
        join_clause += f" FULL OUTER JOIN {_q(alias)} USING ({key_using})"

    select_cols = [_q(k) for k in key_columns] + select_parts
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE __keyed_join__ AS "
        f"SELECT {', '.join(select_cols)} FROM {join_clause}"
    )

    n = len(aliases)
    present_flags = " + ".join(
        f"(CASE WHEN {_q('__present_' + a)} THEN 1 ELSE 0 END)" for a in aliases
    )

    equal_exprs = [
        _column_equality_sql(
            col,
            _q(a1 + "__" + col),
            _q(a2 + "__" + col),
            config,
            tolerance_by_column,
        )
        for col in value_columns
        for a1, a2 in zip(aliases, aliases[1:], strict=False)
    ]
    all_equal_sql = " AND ".join(equal_exprs) if equal_exprs else "TRUE"

    summary_sql = f"""
        SELECT
            SUM(CASE WHEN present_count = {n}
                AND ({all_equal_sql}) THEN 1 ELSE 0 END) AS matched,
            SUM(CASE WHEN present_count = {n}
                AND NOT ({all_equal_sql}) THEN 1 ELSE 0 END) AS mismatched
        FROM (SELECT *, ({present_flags}) AS present_count FROM __keyed_join__)
    """
    matched_raw, mismatched_raw = _fetch_row(con, summary_sql)
    matched_row_count = _sum_as_int(matched_raw)
    mismatched_row_count = _sum_as_int(mismatched_raw)

    only_in: dict[str, int] = {}
    for alias in aliases:
        only_sql = f"""
            SELECT COUNT(*)
            FROM (SELECT *, ({present_flags}) AS present_count FROM __keyed_join__)
            WHERE {_q('__present_' + alias)} AND present_count < {n}
        """
        only_in[alias] = _scalar_query(con, only_sql)

    con.execute("DROP TABLE __keyed_join__")
    return matched_row_count, mismatched_row_count, only_in


def _sanity_check_warnings(
    source_summaries: list[SourceSummary],
    comparison_columns: list[str],
) -> list[str]:
    """Cheap pre-flight checks surfaced as warnings -- never blocks the comparison."""
    warnings: list[str] = []
    row_counts = {s.name: s.row_count for s in source_summaries}
    max_count, min_count = max(row_counts.values()), min(row_counts.values())
    if max_count > 0 and (max_count - min_count) / max_count > 0.2:
        counts_str = ", ".join(f"{name}={count}" for name, count in row_counts.items())
        warnings.append(
            f"Row counts vary by more than 20% across sources ({counts_str}). "
            "Large disparities often indicate a filtered export or a partial load."
        )
    if not comparison_columns:
        warnings.append("No comparison columns remain after applying ignore_columns.")
    return warnings


def run_comparison(
    sources: dict[str, str],
    config: ComparisonConfig,
    connection: duckdb.DuckDBPyConnection | None = None,
    column_mapping: dict[str, dict[str, str]] | None = None,
) -> ComparisonResult:
    """Run an N-way comparison across the given sources.

    Parameters
    ----------
    sources:
        Mapping of source name -> file path (.csv/.tsv/.parquet). DuckDB's
        native readers handle parsing.
    config:
        A ComparisonConfig controlling comparison behavior.
    connection:
        Optional existing DuckDB connection to reuse (e.g. an in-memory
        one shared across a longer-lived ComparisonSession) instead of
        opening a new one. The caller retains ownership when supplied.
    column_mapping:
        An explicitly-accepted column rename mapping (source name ->
        {original_column: canonical_column}), as returned by
        `schema.suggest_column_mapping` and reviewed by the caller.
        Applied before schema validation, so sources that only differ
        by column naming can still be compared. `None` (the default)
        applies no renaming -- schemas must then match exactly.
    """
    import duckdb as duckdb_module

    owns_connection = connection is None
    con = connection or duckdb_module.connect(database=":memory:")
    try:
        aliases = list(sources.keys())
        source_columns = get_source_columns(con, sources, column_mapping)
        row_counts = {
            alias: _scalar_query(con, f"SELECT COUNT(*) FROM {_q(alias)}") for alias in aliases
        }

        comparison_columns = _comparison_columns(source_columns, config.ignore_columns)
        _validate_config(config, comparison_columns)

        source_summaries = [
            SourceSummary(
                name=alias,
                row_count=row_counts[alias],
                column_count=len(source_columns[alias]),
            )
            for alias in aliases
        ]
        result = ComparisonResult(sources=source_summaries)

        if config.key_columns:
            matched, mismatched, only_in = _mode_keyed(con, aliases, comparison_columns, config)
            result.matched_row_count = matched
            result.mismatched_row_count = mismatched
            result.only_in = only_in
        else:
            matched, only_in = _mode_full_row(con, aliases, comparison_columns)
            result.matched_row_count = matched
            result.mismatched_row_count = 0
            result.only_in = only_in

        if config.sanity_check_mode:
            result.warnings.extend(_sanity_check_warnings(source_summaries, comparison_columns))

        return result
    finally:
        if owns_connection:
            con.close()
