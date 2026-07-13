# duckdiff

N-way, order-independent comparison of large record files, powered by [DuckDB](https://duckdb.org/).

> **Status: early scaffolding.** The public API below is stable by intent,
> but `ComparisonSession.compare()` currently raises `NotImplementedError` —
> the comparison engine itself is the next phase of work.

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

## Design principles

- **Minimal by default.** Every optional behavior (fuzzy column mapping,
  numeric tolerances, sanity-check mode) is off until you turn it on.
- **One engine, thin surfaces.** `ComparisonSession` is where all the logic
  lives. The CLI is a thin wrapper around it, and any future UI will be too.
- **Row identity via content hash.** Rows are matched across sources using
  an order-independent hash over the key columns, not row position.

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

print(result)
```

## Project layout

```
src/duckdiff/
├── session.py      # ComparisonSession — the real engine, everything else wraps this
├── config.py        # ComparisonConfig — minimal-by-default options
├── comparator.py    # N-way DuckDB comparison logic (stub — next phase)
├── schema.py         # Fuzzy column-mapping suggestions (stub — next phase)
├── results.py        # ComparisonResult / SourceSummary data structures
├── exceptions.py       # DuckDiffError hierarchy
└── cli.py               # Thin argparse-based CLI wrapper
```

## Roadmap

- [x] Project scaffolding, config/result data model, session API surface
- [ ] Core N-way comparison engine (DuckDB, content-hash row matching)
- [ ] Fuzzy column-mapping suggestions
- [ ] Tolerance-based comparison + sanity-check mode
- [ ] UI (thin wrapper over `ComparisonSession`, TBD)

## License

MIT
