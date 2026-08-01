"""Streamlit UI for duckdiff -- a thin wrapper over ComparisonSession.

Run via `duckdiff ui`, or directly with `streamlit run src/duckdiff/ui/app.py`
for development. Every source is referenced by file path, never uploaded --
DuckDB reads straight off disk, same as the CLI, so large files never pass
through this process's memory as raw bytes.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb
import streamlit as st

from duckdiff.config import ComparisonConfig
from duckdiff.config import ComparisonConfig, ToleranceRule
from duckdiff.exceptions import DuckDiffError, SchemaMismatchError
from duckdiff.results import ComparisonResult
from duckdiff.session import ComparisonSession

MIN_SOURCES = 2

_STATE_DEFAULTS = {
    "pending_session": None,
    "pending_error": None,
    "suggested_mapping": None,
    "last_result_markdown": None,
    "last_result": None,
    "last_error": None,
    "result_session": None,
}


def _new_source(name: str) -> dict[str, str]:
    return {"id": uuid.uuid4().hex, "name": name, "path": ""}


def _init_state() -> None:
    if "sources" not in st.session_state:
        st.session_state.sources = [_new_source("a"), _new_source("b")]
    for key, default in _STATE_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default


def _render_sources() -> None:
    st.subheader("Sources")
    remove_id = None
    for source in st.session_state.sources:
        row_id = source["id"]
        name_col, path_col, remove_col = st.columns([2, 5, 1])
        source["name"] = name_col.text_input("Name", value=source["name"], key=f"name_{row_id}")
        source["path"] = path_col.text_input("Path", value=source["path"], key=f"path_{row_id}")
        can_remove = len(st.session_state.sources) > MIN_SOURCES
        if remove_col.button("Remove", key=f"remove_{row_id}", disabled=not can_remove):
            remove_id = row_id

    if remove_id is not None:
        st.session_state.sources = [
            s for s in st.session_state.sources if s["id"] != remove_id
        ]
        st.rerun()

    if st.button("+ Add source"):
        next_letter = chr(ord("a") + len(st.session_state.sources))
        st.session_state.sources.append(_new_source(next_letter))
        st.rerun()


def _parse_kv_floats(raw: str) -> list[tuple[str, float]]:
    """Parse a comma-separated 'column=value' string into (column, float) pairs.
    Silently skips malformed entries so a half-typed input doesn't block compare."""
    result = []
    for item in raw.split(","):
        item = item.strip()
        if "=" not in item:
            continue
        col, _, val = item.partition("=")
        col = col.strip()
        try:
            result.append((col, float(val.strip())))
        except ValueError:
            continue
    return result


def _build_config() -> ComparisonConfig:
    raw_keys = st.session_state.get("key_columns_input", "")
    key_columns = [c.strip() for c in raw_keys.split(",") if c.strip()]

    raw_ignore = st.session_state.get("ignore_columns_input", "")
    ignore_columns = [c.strip() for c in raw_ignore.split(",") if c.strip()]

    abs_pairs = _parse_kv_floats(st.session_state.get("tolerance_abs_input", ""))
    rel_pairs = _parse_kv_floats(st.session_state.get("tolerance_rel_input", ""))
    tolerance_by_col: dict[str, ToleranceRule] = {}
    for col, val in abs_pairs:
        tolerance_by_col.setdefault(col, ToleranceRule(column=col)).absolute = val
    for col, val in rel_pairs:
        tolerance_by_col.setdefault(col, ToleranceRule(column=col)).relative = val
    tolerances = list(tolerance_by_col.values())

    return ComparisonConfig(
        key_columns=key_columns,
        ignore_columns=ignore_columns,
        tolerances=tolerances,
        case_sensitive=not st.session_state.get("case_insensitive", False),
        sanity_check_mode=st.session_state.get("sanity_check", False),
        auto_intersect_columns=st.session_state.get("auto_intersect", False),
        enable_fuzzy_column_mapping=True,
        include_mismatch_samples=bool(key_columns),
        mismatch_sample_size=3,
    )


def _default_export_path() -> str:
    """Derive a sensible default export path from source a's location."""
    for source in st.session_state.sources:
        if source["name"] == "a" and source["path"]:
            parent = Path(source["path"]).parent
            return str(parent / "duckdiff_result.csv")
    return "duckdiff_result.csv"


def _format_result_markdown(result: ComparisonResult) -> str:
    lines = ["**Sources**"]
    for source in result.sources:
        lines.append(f"- {source.name}: {source.row_count:,} rows, {source.column_count} columns")

    lines.append("")
    lines.append(f"**Matched:** {result.matched_row_count:,}")
    lines.append(f"**Mismatched:** {result.mismatched_row_count:,}")
    for name, count in result.only_in.items():
        lines.append(f"**Only in {name}:** {count:,}")

    if result.warnings:
        lines.append("")
        lines.append("**Warnings:**")
        for warning in result.warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines)


def _close_pending_session() -> None:
    if st.session_state.pending_session is not None:
        st.session_state.pending_session.close()
    st.session_state.pending_session = None
    st.session_state.pending_error = None
    st.session_state.suggested_mapping = None


def _close_result_session() -> None:
    if st.session_state.result_session is not None:
        st.session_state.result_session.close()
    st.session_state.result_session = None


def _reset_display_state() -> None:
    _close_pending_session()
    _close_result_session()
    st.session_state.last_result_markdown = None
    st.session_state.last_result = None
    st.session_state.last_error = None


def _run_compare() -> None:
    _reset_display_state()

    config = _build_config()
    session = ComparisonSession(config)
    for source in st.session_state.sources:
        if source["name"] and source["path"]:
            session.add_source(source["name"], source["path"])

    try:
        result = session.compare()
    except SchemaMismatchError as exc:
        st.session_state.pending_session = session
        st.session_state.pending_error = str(exc)
    except (DuckDiffError, ValueError, duckdb.Error) as exc:
        st.session_state.last_error = str(exc)
        session.close()
    else:
        st.session_state.last_result_markdown = _format_result_markdown(result)
        st.session_state.last_result = result
        # Keep session alive -- export_mismatches() needs the same
        # connection and registered source views to still be open.
        st.session_state.result_session = session


def _render_fuzzy_mapping_flow() -> None:
    session = st.session_state.pending_session
    if session is None:
        return

    st.error(f"Error: {st.session_state.pending_error}")
    st.subheader("Resolve schema mismatch")

    if st.session_state.suggested_mapping is None:
        if st.button("Suggest column mapping"):
            st.session_state.suggested_mapping = session.suggest_column_mapping()
            st.rerun()
        return

    mapping = st.session_state.suggested_mapping
    if not mapping:
        st.info("No fuzzy column-mapping suggestions found.")
        return

    st.write("Suggested column mapping:")
    for source_name, columns in mapping.items():
        for original, canonical in columns.items():
            st.write(f"- {source_name}.{original} \u2192 {canonical}")

    if st.button("Apply and retry", type="primary"):
        session.apply_column_mapping(mapping)
        try:
            result = session.compare()
        except (DuckDiffError, ValueError, duckdb.Error) as exc:
            st.session_state.last_error = str(exc)
            _close_pending_session()
        else:
            st.session_state.last_result_markdown = _format_result_markdown(result)
            st.session_state.last_result = result
            # Promote the pending session to result_session so export
            # can use it -- it's already open with sources registered.
            st.session_state.result_session = session
            st.session_state.pending_session = None
            st.session_state.pending_error = None
            st.session_state.suggested_mapping = None
        finally:
            st.rerun()


def _render_mismatch_samples(result: ComparisonResult) -> None:
    """Show a bounded preview of mismatched rows as a table."""
    if not result.mismatch_samples:
        return

    st.subheader("Mismatch preview (up to 3 rows)")

    # Build a flat list of dicts for st.table -- one row per MismatchSample,
    # key columns first, then one column per differing field showing
    # "a: X  /  b: Y" so the user can see both values side by side.
    source_names = [s.name for s in result.sources]
    rows = []
    for sample in result.mismatch_samples:
        row: dict[str, str] = {k: str(v) for k, v in sample.key.items()}
        for col, values in sample.differences.items():
            parts = [f"{src}: {values.get(src, 'N/A')}" for src in source_names]
            row[col] = "  /  ".join(parts)
        rows.append(row)

    st.table(rows)


def _render_export_section(result: ComparisonResult) -> None:
    """Export path input + button, only shown when there's something to export."""
    has_mismatches = result.mismatched_row_count > 0
    has_only_in = any(count > 0 for count in result.only_in.values())
    if not (has_mismatches or has_only_in):
        return

    st.subheader("Export detail")
    export_path = st.text_input(
        "Output path (base filename)",
        value=_default_export_path(),
        help=(
            "duckdiff will write separate files derived from this name: "
            "e.g. result_mismatches.csv, result_only_in_a.csv, etc."
        ),
        key="export_path_input",
    )

    if st.button("Export to files"):
        session = st.session_state.result_session
        if session is None:
            st.error("No active session -- run Compare first.")
            return
        try:
            session.export_mismatches(export_path)
            base = Path(export_path)
            stem, suffix = base.stem, base.suffix or ".csv"
            written = [f"{stem}_mismatches{suffix}"] + [
                f"{stem}_only_in_{s.name}{suffix}" for s in result.sources
            ]
            st.success(
                f"Written to {base.parent}:\n" + "\n".join(f"- {f}" for f in written)
            )
        except (DuckDiffError, ValueError, duckdb.Error, OSError) as exc:
            st.error(f"Export failed: {exc}")


def main() -> None:
    st.set_page_config(page_title="duckdiff", layout="centered")
    st.title("duckdiff")
    st.caption("N-way, order-independent comparison of large record files.")

    _init_state()
    _render_sources()

    st.subheader("Options")
    st.text_input(
        "Key columns (comma-separated)",
        key="key_columns_input",
        help="Leave blank for full-row (order-independent, duplicate-aware) comparison.",
    )
    st.text_input(
        "Ignore columns (comma-separated)",
        key="ignore_columns_input",
        help="Columns to exclude from comparison entirely, e.g. updated_at, created_at.",
    )
    st.text_input(
        "Absolute tolerances (e.g. amount=0.01, qty=5)",
        key="tolerance_abs_input",
        help="Per-column absolute tolerance. Requires key columns.",
    )
    st.text_input(
        "Relative tolerances (e.g. amount=0.01 means within 1%)",
        key="tolerance_rel_input",
        help="Per-column relative tolerance as a fraction. Requires key columns.",
    )
    st.checkbox("Case-insensitive", key="case_insensitive")
    st.checkbox("Sanity check", key="sanity_check")
    st.checkbox(
        "Auto-intersect columns",
        key="auto_intersect",
        help="Compare only columns shared by all sources. Columns unique to one "
        "source are excluded with a warning instead of failing outright.",
    )

    if st.button("Compare", type="primary"):
        _run_compare()

    _render_fuzzy_mapping_flow()

    if st.session_state.last_error:
        st.error(f"Error: {st.session_state.last_error}")

    if st.session_state.last_result_markdown:
        st.markdown(st.session_state.last_result_markdown)

    if st.session_state.last_result is not None:
        _render_mismatch_samples(st.session_state.last_result)
        _render_export_section(st.session_state.last_result)


main()