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
  it never guesses and applies one silently. *(Not yet implemented.)*

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
- **Exact schema match required (for now).** Comparison columns must match
  exactly by name across sources once `ignore_columns` is applied — a
  `SchemaMismatchError` is raised otherwise. Fuzzy mapping will relax this.

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

## Project layout

```
src/duckdiff/
├── session.py      # ComparisonSession — the real engine, everything else wraps this
├── config.py        # ComparisonConfig — minimal-by-default options
├── comparator.py    # N-way DuckDB comparison logic (both modes implemented)
├── schema.py         # Fuzzy column-mapping suggestions (stub — next phase)
├── results.py        # ComparisonResult / SourceSummary data structures
├── exceptions.py       # DuckDiffError hierarchy
└── cli.py               # Thin argparse-based CLI wrapper
```

## Roadmap

- [x] Project scaffolding, config/result data model, session API surface
- [x] Core N-way comparison engine (full-row multiset mode + keyed mode with tolerance)
- [ ] Fuzzy column-mapping suggestions
- [ ] `--dry-run` cost preview for large comparisons
- [ ] UI (thin wrapper over `ComparisonSession`, TBD)

## License

MIT
