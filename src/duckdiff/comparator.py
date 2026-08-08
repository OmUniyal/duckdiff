"""Core N-way comparison engine, powered by DuckDB."""

from __future__ import annotations

from pathlib import Path
import os
from typing import TYPE_CHECKING

from duckdiff.config import ComparisonConfig, ToleranceRule
from duckdiff.exceptions import ConfigurationError, SchemaMismatchError
from duckdiff.results import ComparisonResult, MismatchSample, SourceSummary, KeyColumnSuggestion

if TYPE_CHECKING:
    import duckdb

_READERS = {".csv", ".tsv", ".parquet"}


def _extension(path: str) -> str:
    filename = path.rsplit("/", 1)[-1]
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def _reader_sql(path: str) -> str:
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
    return '"' + identifier.replace('"', '""') + '"'


def _fetch_row(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[object, ...]:
    row = con.execute(sql).fetchone()
    assert row is not None, f"Expected exactly one row, got none, for query: {sql}"
    return row


def _scalar_query(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    value = _fetch_row(con, sql)[0]
    assert isinstance(value, int)
    return value


def _sum_as_int(value: object) -> int:
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
    return {
        alias: _register_source(con, alias, path, (column_mapping or {}).get(alias))
        for alias, path in sources.items()
    }


def _comparison_columns(
    source_columns: dict[str, list[str]],
    ignore_columns: list[str],
    auto_intersect: bool = False,
    key_columns: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Determine the columns to compare and return (columns, warnings).

    With auto_intersect=False (the default): requires an exact column-set
    match across all sources after ignore_columns is applied, raising
    SchemaMismatchError otherwise.

    With auto_intersect=True: computes the intersection of all sources'
    column sets and drops non-shared columns, surfacing a warning for
    each source that had columns dropped. Raises ConfigurationError if
    the intersection is empty (zero columns left to compare -- almost
    certainly a mistake), or if only key columns remain in keyed mode.
    """
    ignore = set(ignore_columns)
    column_sets = {name: set(cols) - ignore for name, cols in source_columns.items()}

    if not auto_intersect:
        reference_name, reference_set = next(iter(column_sets.items()))
        for name, cols in column_sets.items():
            if cols != reference_set:
                missing = reference_set - cols
                extra = cols - reference_set
                raise SchemaMismatchError(
                    f"Source '{name}' schema doesn't match source '{reference_name}' "
                    f"after applying ignore_columns. Missing here: {sorted(missing)}. "
                    f"Extra here: {sorted(extra)}. Use column mapping to reconcile "
                    f"mismatched names, or add them to ignore_columns, or pass "
                    f"auto_intersect_columns=True to compare only shared columns."
                )
        reference_cols = source_columns[reference_name]
        return [c for c in reference_cols if c in reference_set], []

    # Auto-intersect: keep only columns present in every source.
    shared = set.intersection(*column_sets.values()) if column_sets else set()

    if not shared:
        raise ConfigurationError(
            "No columns are shared across all sources after applying ignore_columns. "
            "There is nothing to compare. Check that your sources have overlapping "
            "column names, or review your ignore_columns setting."
        )

    key_column_set = set(key_columns or [])
    if key_column_set and not (shared - key_column_set):
        raise ConfigurationError(
            "No columns are shared across all sources after applying ignore_columns. "
            "There is nothing to compare once key_columns are excluded. "
            "Check that your sources share at least one non-key comparison column."
        )

    warnings: list[str] = []
    for name, cols in column_sets.items():
        dropped = sorted(cols - shared)
        if dropped:
            warnings.append(
                f"Source '{name}': columns {dropped} not present in all sources "
                f"-- excluded from comparison (auto_intersect_columns=True)."
            )

    # Use the first source's column order for the intersection, for determinism.
    first_cols = source_columns[next(iter(source_columns))]
    return [c for c in first_cols if c in shared], warnings


def _validate_config(config: ComparisonConfig, comparison_columns: list[str]) -> None:
    if config.tolerances and not config.key_columns:
        raise ConfigurationError(
            "Tolerance rules require key_columns -- approximate equality needs "
            "two aligned rows to compare specific values against. Set "
            "key_columns, or drop the tolerance rules for a full-row "
            "content comparison."
        )
    if config.include_mismatch_samples and not config.key_columns:
        raise ConfigurationError(
            "include_mismatch_samples requires key_columns -- which column "
            "differs for this row needs an aligned row to compare against. "
            "Set key_columns, or turn this off for a full-row comparison."
        )
    comparison_set = set(comparison_columns)
    unknown_tolerance_cols = {t.column for t in config.tolerances} - comparison_set
    if unknown_tolerance_cols:
        raise ConfigurationError(
            f"Tolerance rule(s) reference unknown column(s): {sorted(unknown_tolerance_cols)}"
        )
    unknown_keys = set(config.key_columns) - comparison_set
    if unknown_keys:
        raise ConfigurationError(
            f"key_columns reference unknown column(s): {sorted(unknown_keys)}"
        )


def _tolerance_predicate(rule: ToleranceRule, left: str, right: str) -> str:
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


def _build_keyed_join(
    con: duckdb.DuckDBPyConnection,
    aliases: list[str],
    comparison_columns: list[str],
    config: ComparisonConfig,
) -> tuple[list[str], dict[str, str], str]:
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

    present_flags = " + ".join(
        f"(CASE WHEN {_q('__present_' + a)} THEN 1 ELSE 0 END)" for a in aliases
    )

    column_equal_sql: dict[str, str] = {}
    for col in value_columns:
        pair_checks = [
            _column_equality_sql(
                col, _q(a1 + "__" + col), _q(a2 + "__" + col), config, tolerance_by_column
            )
            for a1, a2 in zip(aliases, aliases[1:], strict=False)
        ]
        column_equal_sql[col] = " AND ".join(pair_checks) if pair_checks else "TRUE"

    return value_columns, column_equal_sql, present_flags


def _keyed_summary(
    con: duckdb.DuckDBPyConnection,
    aliases: list[str],
    column_equal_sql: dict[str, str],
    present_flags: str,
    n: int,
) -> tuple[int, int, dict[str, int]]:
    all_equal_sql = " AND ".join(column_equal_sql.values()) if column_equal_sql else "TRUE"
    base = f"(SELECT *, ({present_flags}) AS present_count FROM __keyed_join__)"

    summary_sql = f"""
        SELECT
            SUM(CASE WHEN present_count = {n}
                AND ({all_equal_sql}) THEN 1 ELSE 0 END) AS matched,
            SUM(CASE WHEN present_count = {n}
                AND NOT ({all_equal_sql}) THEN 1 ELSE 0 END) AS mismatched
        FROM {base}
    """
    matched_raw, mismatched_raw = _fetch_row(con, summary_sql)
    matched_row_count = _sum_as_int(matched_raw)
    mismatched_row_count = _sum_as_int(mismatched_raw)

    only_in: dict[str, int] = {}
    for alias in aliases:
        only_sql = f"""
            SELECT COUNT(*) FROM {base}
            WHERE {_q('__present_' + alias)} AND present_count < {n}
        """
        only_in[alias] = _scalar_query(con, only_sql)

    return matched_row_count, mismatched_row_count, only_in


def _mismatch_melt_sql(
    aliases: list[str],
    key_columns: list[str],
    value_columns: list[str],
    column_equal_sql: dict[str, str],
    present_flags: str,
    n: int,
) -> str:
    key_select = ", ".join(_q(k) for k in key_columns)
    base = f"(SELECT *, ({present_flags}) AS present_count FROM __keyed_join__)"
    column_label = _q("column")

    if not value_columns:
        null_values = ", ".join(f"NULL AS {_q(a + '_value')}" for a in aliases)
        return (
            f"SELECT {key_select}, NULL AS {column_label}, "
            f"{null_values} FROM {base} WHERE FALSE"
        )

    parts = []
    for col in value_columns:
        # Cast to VARCHAR so the melt output has a consistent column type
        # regardless of the source column's native type (DOUBLE, DATE, etc).
        # A UNION ALL across value_columns of mixed types would otherwise
        # require DuckDB to coerce them to a common type, which can fail or
        # produce surprising results.
        value_cols = ", ".join(
            f"CAST({_q(alias + '__' + col)} AS VARCHAR) AS {_q(alias + '_value')}" for alias in aliases
        )
        parts.append(
            f"SELECT {key_select}, '{col}' AS {column_label}, {value_cols} "
            f"FROM {base} "
            f"WHERE present_count = {n} AND NOT ({column_equal_sql[col]})"
        )
    return " UNION ALL ".join(parts)


def _sample_mismatches(
    con: duckdb.DuckDBPyConnection,
    aliases: list[str],
    key_columns: list[str],
    value_columns: list[str],
    column_equal_sql: dict[str, str],
    present_flags: str,
    n: int,
    sample_size: int,
) -> list[MismatchSample]:
    if not value_columns or sample_size <= 0:
        return []

    key_select = ", ".join(_q(k) for k in key_columns)
    all_equal_sql = " AND ".join(column_equal_sql.values())
    base = f"(SELECT *, ({present_flags}) AS present_count FROM __keyed_join__)"

    sample_keys_sql = (
        f"SELECT {key_select} FROM {base} "
        f"WHERE present_count = {n} AND NOT ({all_equal_sql}) "
        f"ORDER BY {key_select} LIMIT {sample_size}"
    )
    sample_key_rows = con.execute(sample_keys_sql).fetchall()
    if not sample_key_rows:
        return []

    melt_sql = _mismatch_melt_sql(
        aliases, key_columns, value_columns, column_equal_sql, present_flags, n
    )
    placeholder_tuple = "(" + ", ".join(["?"] * len(key_columns)) + ")"
    in_clause = ", ".join([placeholder_tuple] * len(sample_key_rows))
    params = [value for row in sample_key_rows for value in row]
    restricted_sql = f"SELECT * FROM ({melt_sql}) WHERE ({key_select}) IN ({in_clause})"

    cursor = con.execute(restricted_sql, params)
    result_columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()

    samples_by_key: dict[tuple[object, ...], MismatchSample] = {}
    for row in rows:
        row_dict = dict(zip(result_columns, row, strict=False))
        key_values = tuple(row_dict[k] for k in key_columns)
        column_name = row_dict["column"]
        value_by_source = {alias: row_dict[f"{alias}_value"] for alias in aliases}
        sample = samples_by_key.setdefault(
            key_values,
            MismatchSample(key=dict(zip(key_columns, key_values, strict=False))),
        )
        sample.differences[column_name] = value_by_source

    ordered_keys = [tuple(row) for row in sample_key_rows]
    return [samples_by_key[k] for k in ordered_keys if k in samples_by_key]


def _mode_keyed(
    con: duckdb.DuckDBPyConnection,
    aliases: list[str],
    comparison_columns: list[str],
    config: ComparisonConfig,
) -> tuple[int, int, dict[str, int], list[MismatchSample]]:
    value_columns, column_equal_sql, present_flags = _build_keyed_join(
        con, aliases, comparison_columns, config
    )
    n = len(aliases)
    try:
        matched, mismatched, only_in = _keyed_summary(
            con, aliases, column_equal_sql, present_flags, n
        )
        samples: list[MismatchSample] = []
        if config.include_mismatch_samples:
            samples = _sample_mismatches(
                con,
                aliases,
                config.key_columns,
                value_columns,
                column_equal_sql,
                present_flags,
                n,
                config.mismatch_sample_size,
            )
        return matched, mismatched, only_in, samples
    finally:
        con.execute("DROP TABLE __keyed_join__")


def _sanity_check_warnings(
    source_summaries: list[SourceSummary],
    comparison_columns: list[str],
) -> list[str]:
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
    import duckdb as duckdb_module

    owns_connection = connection is None
    con = connection or duckdb_module.connect(database=":memory:")
    try:
        aliases = list(sources.keys())
        source_columns = get_source_columns(con, sources, column_mapping)
        row_counts = {
            alias: _scalar_query(con, f"SELECT COUNT(*) FROM {_q(alias)}") for alias in aliases
        }

        comparison_columns, intersect_warnings = _comparison_columns(
            source_columns,
            config.ignore_columns,
            config.auto_intersect_columns,
            config.key_columns,
        )
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
        result.warnings.extend(intersect_warnings)

        if config.key_columns:
            matched, mismatched, only_in, samples = _mode_keyed(
                con, aliases, comparison_columns, config
            )
            result.matched_row_count = matched
            result.mismatched_row_count = mismatched
            result.only_in = only_in
            result.mismatch_samples = samples
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


def _copy_to_csv(con: duckdb.DuckDBPyConnection, select_sql: str, path: Path) -> None:
    escaped_path = str(path).replace("'", "''")
    con.execute(f"COPY ({select_sql}) TO '{escaped_path}' (HEADER, DELIMITER ',')")


def export_mismatches(
    sources: dict[str, str],
    config: ComparisonConfig,
    output_path: str,
    connection: duckdb.DuckDBPyConnection | None = None,
    column_mapping: dict[str, dict[str, str]] | None = None,
) -> None:
    """Write the full mismatch and only-in detail to disk.

    Given `output_path` (e.g. "result.csv"), writes:
      - "result_mismatches.csv" -- long/melted: one row per key + differing
        column, with one value column per source.
      - "result_only_in_{alias}.csv" for each source -- that source's FULL
        original columns for keys missing from at least one other source.

    Requires config.key_columns.
    """
    import duckdb as duckdb_module

    if not config.key_columns:
        raise ConfigurationError(
            "export_mismatches() requires key_columns -- exporting mismatch/"
            "only-in detail needs aligned rows to compare and report on."
        )

    owns_connection = connection is None
    con = connection or duckdb_module.connect(database=":memory:")
    try:
        aliases = list(sources.keys())
        source_columns = get_source_columns(con, sources, column_mapping)
        comparison_columns, _ = _comparison_columns(
            source_columns,
            config.ignore_columns,
            config.auto_intersect_columns,
            config.key_columns,
        )
        _validate_config(config, comparison_columns)

        value_columns, column_equal_sql, present_flags = _build_keyed_join(
            con, aliases, comparison_columns, config
        )
        n = len(aliases)
        try:
            base_path = Path(output_path)
            stem = base_path.stem
            suffix = base_path.suffix or ".csv"

            melt_sql = _mismatch_melt_sql(
                aliases, config.key_columns, value_columns, column_equal_sql, present_flags, n
            )
            mismatches_path = base_path.with_name(f"{stem}_mismatches{suffix}")
            _copy_to_csv(con, melt_sql, mismatches_path)

            only_in_base = (
                f"(SELECT *, ({present_flags}) AS present_count FROM __keyed_join__)"
            )
            key_select = ", ".join(_q(k) for k in config.key_columns)
            for alias in aliases:
                only_in_keys_sql = (
                    f"SELECT {key_select} FROM {only_in_base} "
                    f"WHERE {_q('__present_' + alias)} AND present_count < {n}"
                )
                export_sql = (
                    f"SELECT {_q(alias)}.* FROM {_q(alias)} "
                    f"JOIN ({only_in_keys_sql}) AS __only_in_keys__ "
                    f"USING ({key_select})"
                )
                only_in_path = base_path.with_name(f"{stem}_only_in_{alias}{suffix}")
                _copy_to_csv(con, export_sql, only_in_path)
        finally:
            con.execute("DROP TABLE __keyed_join__")
    finally:
        if owns_connection:
            con.close()


def dry_run(
    sources: dict[str, str],
    config: ComparisonConfig,
    connection: duckdb.DuckDBPyConnection | None = None,
    column_mapping: dict[str, dict[str, str]] | None = None,
) -> "DryRunResult":
    """Cheap pre-flight preview: schema introspection + file sizes only.

    Registers each source as a DuckDB view (needed to read column names)
    but never scans row data -- no COUNT(*), no joins, no melt queries.
    File sizes come from the OS. Schema compatibility is resolved via the
    same _comparison_columns() path that run_comparison() uses, so the
    dry-run verdict is always consistent with what compare() would do.

    Always returns a DryRunResult -- never raises SchemaMismatchError or
    ConfigurationError. Those are captured in result.would_raise instead,
    so the caller can inspect what would fail before committing to a run.
    """
    from duckdiff.results import DryRunResult, SourcePreview

    import duckdb as duckdb_module

    owns_connection = connection is None
    con = connection or duckdb_module.connect(database=":memory:")
    try:
        aliases = list(sources.keys())
        source_columns = get_source_columns(con, sources, column_mapping)

        previews = [
            SourcePreview(
                name=alias,
                path=sources[alias],
                file_size_bytes=os.path.getsize(sources[alias]),
                columns=source_columns[alias],
            )
            for alias in aliases
        ]

        comparison_columns: list[str] = []
        warnings: list[str] = []
        would_raise: str | None = None

        try:
            comparison_columns, intersect_warnings = _comparison_columns(
                source_columns,
                config.ignore_columns,
                config.auto_intersect_columns,
                config.key_columns,
            )
            warnings.extend(intersect_warnings)
        except (SchemaMismatchError, ConfigurationError) as exc:
            would_raise = str(exc)

        return DryRunResult(
            sources=previews,
            comparison_columns=comparison_columns,
            warnings=warnings,
            would_raise=would_raise,
        )
    finally:
        if owns_connection:
            con.close()


# Heuristic patterns that suggest a column is a measure, not a dimension.
# Candidate key testing skips these -- measures are unlikely to be key columns.
_MEASURE_HINTS = frozenset([
    "revenue", "quantity", "amount", "qty", "count", "total",
    "sales", "price", "cost", "invoice", "member", "value", "#",
])


def _looks_like_measure(col: str) -> bool:
    lower = col.lower()
    return any(hint in lower for hint in _MEASURE_HINTS)


def suggest_key_columns(
    source: str,
    connection: duckdb.DuckDBPyConnection | None = None,
    max_combo_size: int = 6,
) -> list[KeyColumnSuggestion]:
    """Suggest which column(s) uniquely identify rows in a single source file.

    Tests single columns first, then composites in increasing size. Stops
    at the first size that produces at least one unique key -- no point
    testing larger combos if a smaller one already works.

    Columns whose names suggest they are measures (revenue, quantity, etc.)
    are excluded from candidate testing -- they are unlikely to be key
    columns and including them would produce misleading suggestions.

    Returns a list of KeyColumnSuggestion, sorted by distinct_count
    descending (unique keys first). Non-unique candidates are included
    so the caller can see how close each combination gets.
    """
    import duckdb as duckdb_module
    import itertools

    owns_connection = connection is None
    con = connection or duckdb_module.connect(database=":memory:")
    try:
        alias = "__suggest_key_source__"
        all_columns = _register_source(con, alias, source)
        total = _scalar_query(con, f"SELECT COUNT(*) FROM {_q(alias)}")

        dimensions = [c for c in all_columns if not _looks_like_measure(c)]

        results: list[KeyColumnSuggestion] = []
        found_unique = False

        for size in range(1, min(max_combo_size + 1, len(dimensions) + 1)):
            if found_unique:
                break
            size_results: list[KeyColumnSuggestion] = []
            for combo in itertools.combinations(dimensions, size):
                cols = list(combo)
                col_sql = ", ".join(f"{_q(c)}" for c in cols)
                distinct = _scalar_query(
                    con,
                    f"SELECT COUNT(DISTINCT ({col_sql})) FROM {_q(alias)}",
                )
                is_unique = distinct == total
                if is_unique:
                    found_unique = True
                size_results.append(KeyColumnSuggestion(
                    columns=cols,
                    distinct_count=distinct,
                    total_count=total,
                    is_unique=is_unique,
                ))
            results.extend(size_results)

        return sorted(results, key=lambda s: s.distinct_count, reverse=True)
    finally:
        if owns_connection:
            con.close()