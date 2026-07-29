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
  source A", and is required for tolerance-based (approximate) matching.

## Design principles

- **Minimal by default.** Every optional behavior (fuzzy column mapping,
  numeric tolerances, sanity-check mode) is off until you turn it on.
- **One engine, thin surfaces.** `ComparisonSession` is where all the logic
  lives. The CLI is a thin wrapper around it, and any future UI will be too.
- **Exact schema match required, unless a mapping is applied.** Comparison
  columns must match exactly by name across sources once `ignore_columns`
  and any accepted column mapping are applied — `SchemaMismatchError`
  otherwise.

## Install

```bash
pip install -e ".[dev]"
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

## Project layout
```
src/duckdiff/
├── session.py      # ComparisonSession — the real engine, everything else wraps this
├── config.py        # ComparisonConfig — minimal-by-default options
├── comparator.py    # N-way DuckDB comparison logic (both modes implemented)
├── schema.py         # Fuzzy column-mapping suggestions (implemented)
├── results.py        # ComparisonResult / SourceSummary data structures
├── exceptions.py       # DuckDiffError hierarchy
└── cli.py               # Thin argparse-based CLI wrapper (full argument surface)
```

## CLI usage

`duckdiff` has two subcommands: `compare` (run a comparison) and `ui`
(launch the local web UI -- not yet implemented).

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

Errors (schema mismatches, invalid config) print a single `Error: ...` line
to stderr and exit 1 — not a Python traceback.


## UI (in progress)

```bash
pip install -e ".[ui]"
duckdiff ui
```

Launches a local Streamlit app in your browser. Sources are referenced by
**file path only, never uploaded** -- DuckDB reads straight off disk, same
as the CLI, so large files never pass through the app as raw bytes.

Currently implemented: a dynamic add/remove list of sources, key columns,
case-insensitivity, and sanity-check mode, with a working Compare button.
Not yet implemented: `--ignore`/tolerance rules, and the fuzzy-mapping
flow -- both work from the CLI already, just not the UI yet.


## Known limitations

- **CLI errors from DuckDB are passed through verbatim.** `duckdiff`'s own
  errors (`SchemaMismatchError`, `ConfigurationError`) get clean messages,
  but DuckDB-native failures (bad file path, malformed CSV, etc.) print
  DuckDB's raw exception text as-is -- including the generated SQL, e.g.
  `Error: IO Error: No files found that match the pattern "file1.csv"`.
  This is a deliberate simplicity tradeoff: one broad `except duckdb.Error`
  covers every DuckDB failure mode without a growing table of custom
  translations. Safe to see (this is a local CLI over your own files, not
  output shown to anyone else), just not as polished as it could be.


## Roadmap

- [x] Project scaffolding, config/result data model, session API surface
- [x] Core N-way comparison engine (full-row multiset mode + keyed mode with tolerance)
- [x] Fuzzy column-mapping suggestions
- [x] CLI: full argument surface (ignore/tolerance/case/sanity-check), friendly errors
- [x] CLI: interactive fuzzy-mapping flow (suggest -> confirm -> apply)
- [x] UI: core plumbing -- dynamic source list, key columns, Compare, `duckdiff ui` launcher
- [ ] UI: full parameter parity (ignore, tolerance, case-insensitive, sanity-check)
- [ ] UI: interactive fuzzy-mapping flow
- [ ] `--dry-run` cost preview for large comparisons

## License

MIT