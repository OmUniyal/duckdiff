# duckdiff

N-way, order-independent comparison of large record files, powered by [DuckDB](https://duckdb.org/).

## Why

Most diff tools compare exactly two files and assume they fit in memory.
`duckdiff` is built around three things that get in the way of that in practice:

- **N-way comparison.** Compare 2, 3, or 20 sources against each other in
  one pass, not N pairwise diffs.
- **True large-file streaming.** DuckDB's out-of-core execution means
  comparisons aren't bounded by RAM.
- **Interactive fuzzy column mapping.** When schemas don't line up exactly
  (renamed columns, casing differences), `duckdiff` suggests a mapping —
  it never guesses and applies one silently.

## Two comparison modes

- **No `key_columns`** — a row's entire content is its identity. This is a
  true order-independent, duplicate-aware (multiset) comparison: are the
  same records present, regardless of order? Implemented via DuckDB's
  native `INTERSECT ALL` / `EXCEPT ALL`.
- **`key_columns` given** — rows are aligned across sources by key, then
  the remaining columns are diffed per aligned row. This is what lets a
  result distinguish "row X differs in column Y" from "row X is only in
  source A", and is required for tolerance-based (approximate) matching
  and mismatch detail.

## Design principles

- **Minimal by default.** Every optional behavior (fuzzy column mapping,
  numeric tolerances, sanity-check mode, mismatch samples) is off until
  you turn it on.
- **One engine, thin surfaces.** `ComparisonSession` is where all the logic
  lives. The CLI and UI are thin wrappers around it — every surface
  behaves identically.
- **Exact schema match required, unless a mapping is applied.** Comparison
  columns must match exactly by name across sources once `ignore_columns`
  and any accepted column mapping are applied — `SchemaMismatchError`
  otherwise.

## Install

```bash
pip install duckdiff
```

For the web UI:

```bash
pip install "duckdiff[ui]"
```

## Quickstart

```python
from duckdiff import ComparisonSession

with ComparisonSession() as session:
    session.add_source("legacy", "legacy_export.csv")
    session.add_source("new", "new_export.parquet")
    result = session.compare(key_columns=["record_id"])

print(result.matched_row_count, result.mismatched_row_count, result.only_in)
```

Tolerance-based comparison (requires `key_columns`):

```python
from duckdiff import ComparisonSession, ComparisonConfig, ToleranceRule

config = ComparisonConfig(
    key_columns=["record_id"],
    tolerances=[ToleranceRule(column="amount", absolute=0.01)],
)
with ComparisonSession(config) as session:
    session.add_source("legacy", "legacy_export.csv")
    session.add_source("new", "new_export.parquet")
    result = session.compare()
```

Reconciling renamed columns (fuzzy suggestions, nothing auto-applied):

```python
from duckdiff import ComparisonSession, ComparisonConfig

config = ComparisonConfig(enable_fuzzy_column_mapping=True)
with ComparisonSession(config) as session:
    session.add_source("legacy", "legacy_export.csv")   # has 'cust_id'
    session.add_source("new", "new_export.parquet")     # has 'customer_id'

    suggestion = session.suggest_column_mapping()  # {'legacy': {'cust_id': 'customer_id'}}
    session.apply_column_mapping(suggestion)        # explicit opt-in, review first

    result = session.compare(key_columns=["customer_id"])
```

Mismatch detail — bounded preview in the result, full export to disk:

```python
from duckdiff import ComparisonSession, ComparisonConfig

config = ComparisonConfig(
    key_columns=["record_id"],
    include_mismatch_samples=True,   # up to 3 rows in result.mismatch_samples
    mismatch_sample_size=3,
)
with ComparisonSession(config) as session:
    session.add_source("legacy", "legacy_export.csv")
    session.add_source("new", "new_export.parquet")
    result = session.compare()

    for sample in result.mismatch_samples:
        print(sample.key, sample.differences)

    # Full export -- streams to disk, not memory-bounded
    # Writes: result_mismatches.csv, result_only_in_legacy.csv,
    #         result_only_in_new.csv
    session.export_mismatches("result.csv")
```

## Mismatch export format

`export_mismatches("result.csv")` derives filenames from the given base path
and writes:

- **`result_mismatches.csv`** — long/melted format, one row per (key,
  differing column), with one value column per source:

```
record_id, column,  legacy_value, new_value
42,        amount,  10.00,        10.03
```

- **`result_only_in_{source}.csv`** — one file per source, containing
  the full original columns (not just comparison columns) for keys missing
  from at least one other source. Empty files (headers only) are written
  when there's nothing to report.

## Project layout

```
src/duckdiff/
├── session.py      # ComparisonSession — the real engine, everything else wraps this
├── config.py       # ComparisonConfig — minimal-by-default options
├── comparator.py   # N-way DuckDB comparison logic (both modes, mismatch detail, export)
├── schema.py       # Fuzzy column-mapping suggestions
├── results.py      # ComparisonResult / SourceSummary / MismatchSample / KeyColumnSuggestion
├── exceptions.py   # DuckDiffError hierarchy
├── cli.py          # Thin CLI wrapper (compare/ui subcommands)
└── ui/
└── app.py      # Streamlit web UI
```

## CLI usage

`duckdiff` has three subcommands: `compare` (run a comparison), `keys`
(discover key columns), and `ui` (launch the local web UI). Use
`duckdiff --version` to print the installed version.

```bash
duckdiff --version
```

```bash
duckdiff compare legacy=legacy.csv new=new.csv --key customer_id \
    --ignore updated_at \
    --tolerance-abs amount=0.01 \
    --sanity-check
```

- `--key` — repeatable, for composite keys. Omit entirely for full-row
  (order-independent, duplicate-aware) comparison instead.
- `--ignore COLUMN` — repeatable, excludes a column from comparison.
- `--tolerance-abs COLUMN=VALUE` / `--tolerance-rel COLUMN=VALUE` — repeatable;
  a column can have both. Requires `--key`.
- `--case-insensitive`, `--sanity-check` — flags.
- `--fuzzy-map` — on a schema mismatch, suggest a column mapping and offer
  to apply it (with a y/N confirmation) instead of failing outright.
  `--yes`/`-y` skips the confirmation.
- `--dry-run` — preview schema compatibility and file sizes without scanning
  any rows. Shows each source's file size and column list, the resolved
  comparison columns (or the schema error that `compare` would raise), and
  any auto-intersect warnings. Useful before running a large comparison to
  confirm the config is correct.

Errors (schema mismatches, invalid config) print a single `Error: ...` line
to stderr and exit 1 — not a Python traceback.

### Discovering key columns

```bash
duckdiff keys a=data.csv
```

Scans a single file and suggests which column(s) uniquely identify each
row -- useful when you're not sure which `--key` to pass to `compare`.
Columns with numeric measure types (DOUBLE, FLOAT, DECIMAL) are excluded
automatically -- integer and string columns are always tested as candidates.
Prints unique keys first, with suggested `--key` flags ready to copy into
your `compare` command.

## UI

```bash
duckdiff ui
```

Launches a local Streamlit app in your browser. Sources are referenced by
**file path only, never uploaded** — DuckDB reads straight off disk, same
as the CLI, so large files never pass through the app as raw bytes.

Features: dynamic add/remove source list, all comparison options (key
columns, ignore columns, tolerances, case-insensitivity, sanity check),
interactive fuzzy-mapping retry flow on schema mismatches, a 3-row mismatch
preview after each comparison, and an export-to-files button with a
pre-filled output path derived from the first source's location.

## Known limitations

- **CLI errors from DuckDB are passed through verbatim.** `duckdiff`'s own
  errors (`SchemaMismatchError`, `ConfigurationError`) get clean messages,
  but DuckDB-native failures (bad file path, malformed CSV, etc.) print
  DuckDB's raw exception text as-is — including the generated SQL, e.g.
  `Error: IO Error: No files found that match the pattern "file1.csv"`.
  This is a deliberate simplicity tradeoff: one broad `except duckdb.Error`
  covers every DuckDB failure mode without a growing table of custom
  translations.
- **Exact schema match required by default.** Columns that exist in one
  source but not another must be listed in `ignore_columns` or reconciled
  via fuzzy column mapping before a comparison can run — unless
  `auto_intersect_columns=True` is set, which drops non-shared columns
  automatically and surfaces them as warnings instead.

## Roadmap

- [x] Project scaffolding, config/result data model, session API surface
- [x] Core N-way comparison engine (full-row multiset mode + keyed mode with tolerance)
- [x] Fuzzy column-mapping suggestions
- [x] CLI: full argument surface (ignore/tolerance/case/sanity-check), friendly errors
- [x] CLI: interactive fuzzy-mapping flow (suggest -> confirm -> apply)
- [x] CLI: split into `compare`/`ui` subcommands
- [x] UI: full feature surface (sources, all options, fuzzy-mapping flow, mismatch preview, export)
- [x] Mismatch detail: bounded sample in result + full streamed export to disk
- [x] `--dry-run` cost preview for large comparisons
- [x] Key column discovery (`duckdiff keys` suggests unique key columns for a source file)
- [x] Auto-intersect differing schemas (`auto_intersect_columns=True` compares only shared columns, warns about dropped ones)

## License

MIT