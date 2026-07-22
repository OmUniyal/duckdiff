"""Streamlit UI for duckdiff -- a thin wrapper over ComparisonSession.

Run via `duckdiff ui`, or directly with `streamlit run src/duckdiff/ui/app.py`
for development. Every source is referenced by file path, never uploaded --
DuckDB reads straight off disk, same as the CLI, so large files never pass
through this process's memory as raw bytes.
"""

from __future__ import annotations

import uuid

import duckdb
import streamlit as st

from duckdiff.config import ComparisonConfig
from duckdiff.exceptions import DuckDiffError, SchemaMismatchError
from duckdiff.results import ComparisonResult
from duckdiff.session import ComparisonSession

MIN_SOURCES = 2

_STATE_DEFAULTS = {
    "pending_session": None,
    "pending_error": None,
    "suggested_mapping": None,
    "last_result_markdown": None,
    "last_error": None,
}


def _new_source(name: str) -> dict[str, str]:
    # A stable id assigned once at creation, NOT the list index -- if we
    # keyed widgets by index, removing a source from the middle of the
    # list would shift every later source's index down by one, and
    # Streamlit's widget state (keyed by that index) would then show
    # each shifted row's OLD stale value instead of its actual current
    # one. A stable per-row id sidesteps that entirely.
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


def _build_config() -> ComparisonConfig:
    raw_keys = st.session_state.get("key_columns_input", "")
    key_columns = [c.strip() for c in raw_keys.split(",") if c.strip()]
    return ComparisonConfig(
        key_columns=key_columns,
        case_sensitive=not st.session_state.get("case_insensitive", False),
        sanity_check_mode=st.session_state.get("sanity_check", False),
        # Always on in the UI. Unlike the CLI (where --fuzzy-map and --yes
        # are two separate, deliberate flags a script could pass without a
        # human present), here the "Apply and retry" button click itself
        # IS the explicit, in-the-moment human consent -- there's no
        # unattended caller in this surface who could trigger a mapping
        # apply without a person clicking it.
        enable_fuzzy_column_mapping=True,
    )


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
    """Tear down any in-progress fuzzy-mapping retry flow, closing its
    DuckDB connection."""
    if st.session_state.pending_session is not None:
        st.session_state.pending_session.close()
    st.session_state.pending_session = None
    st.session_state.pending_error = None
    st.session_state.suggested_mapping = None


def _reset_display_state() -> None:
    """Clear everything shown from a previous attempt -- called at the
    start of a fresh Compare click, so an old result/error doesn't linger
    alongside a brand new attempt."""
    _close_pending_session()
    st.session_state.last_result_markdown = None
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
        # Keep the session (and its connection) alive -- the fuzzy-mapping
        # flow below needs to call suggest_column_mapping() and, if
        # accepted, compare() again on this SAME session.
        st.session_state.pending_session = session
        st.session_state.pending_error = str(exc)
    except (DuckDiffError, ValueError, duckdb.Error) as exc:
        st.session_state.last_error = str(exc)
        session.close()
    else:
        st.session_state.last_result_markdown = _format_result_markdown(result)
        session.close()


def _render_fuzzy_mapping_flow() -> None:
    session = st.session_state.pending_session
    if session is None:
        return

    # Re-displayed on EVERY rerun while pending, not just the run where
    # Compare was clicked -- Streamlit reruns the whole script on each
    # subsequent click (e.g. "Suggest column mapping"), and a one-off
    # st.error() call inside _run_compare() would vanish on that next run.
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
        else:
            st.session_state.last_result_markdown = _format_result_markdown(result)
        finally:
            # This branch is reached AFTER the error/suggestion panel
            # above has already been rendered in this same script pass --
            # clearing session_state here doesn't un-render that. Forcing
            # a rerun discards this pass entirely and starts a clean one,
            # where pending_session is None and only the final
            # last_result_markdown/last_error (set above) gets shown.
            _close_pending_session()
            st.rerun()


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
    st.checkbox("Case-insensitive", key="case_insensitive")
    st.checkbox("Sanity check", key="sanity_check")

    if st.button("Compare", type="primary"):
        _run_compare()

    _render_fuzzy_mapping_flow()

    if st.session_state.last_error:
        st.error(f"Error: {st.session_state.last_error}")
    if st.session_state.last_result_markdown:
        st.markdown(st.session_state.last_result_markdown)


main()