"""Column-mapping utilities.

Fuzzy column-name suggestions are always surfaced to the caller for
review — they are never auto-applied to a comparison run. This module
only proposes; ComparisonSession decides what, if anything, gets used.
"""

from __future__ import annotations


def suggest_column_mapping(
    source_columns: dict[str, list[str]],
    threshold: float = 0.85,
) -> dict[str, dict[str, str]]:
    """Suggest a column-name mapping across sources with mismatched schemas.

    Parameters
    ----------
    source_columns:
        Mapping of source name -> list of column names as they appear
        in that source.
    threshold:
        Minimum similarity score (0-1) for a suggested match to be
        included in the result.

    Returns
    -------
    A mapping of source name -> {original_column: suggested_canonical_name}.
    Nothing here is applied automatically; the caller reviews and opts in
    via ComparisonSession.apply_column_mapping().
    """
    raise NotImplementedError("Fuzzy column mapping lands in the next phase.")
