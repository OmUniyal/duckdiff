"""Column-mapping utilities.

Fuzzy column-name suggestions are always surfaced to the caller for
review -- they are never auto-applied to a comparison run. This module
only proposes; ComparisonSession decides what, if anything, gets used.

The matching algorithm is deliberately simple: normalize each column
name (lowercase, strip separators), score every candidate/target pair
with Python's stdlib difflib.SequenceMatcher, and greedily assign each
candidate to its best-scoring, not-yet-used target above `threshold`.
No extra dependency, and a naive-but-inspectable baseline -- see
`_best_matches` for why greedy (not globally optimal) is good enough
for v1.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def _normalize(name: str) -> str:
    """Strip case, separators, and other formatting noise from a column name.

    'cust_id', 'CustID', and 'Cust Id' should all compare as the same
    underlying content -- only the actual letters/digits matter.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _similarity(a: str, b: str) -> float:
    """Similarity ratio (0-1) between two column names, on normalized forms."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _best_matches(candidates: list[str], targets: list[str], threshold: float) -> dict[str, str]:
    """Greedily assign each candidate to its best-scoring, not-yet-used target.

    Greedy rather than a globally optimal (e.g. Hungarian-algorithm)
    assignment: simpler to reason about and fast, at the cost of
    occasionally locking in a locally-best match that blocks a better
    pairing for a later candidate. Candidates are processed in their
    given order, so that order can matter for which of two candidates
    "wins" a contested target -- acceptable for the column counts this
    is meant for (tens, not thousands); worth revisiting if that stops
    holding.
    """
    used_targets: set[str] = set()
    result: dict[str, str] = {}
    for candidate in candidates:
        best_target: str | None = None
        best_score = 0.0
        for target in targets:
            if target in used_targets:
                continue
            score = _similarity(candidate, target)
            if score > best_score:
                best_target, best_score = target, score
        if best_target is not None and best_score >= threshold:
            result[candidate] = best_target
            used_targets.add(best_target)
    return result


def suggest_column_mapping(
    source_columns: dict[str, list[str]],
    threshold: float = 0.6,
) -> dict[str, dict[str, str]]:
    """Suggest a column-name mapping across sources with mismatched schemas.

    The first source (by dict iteration order) is treated as the
    reference; every other source's non-matching columns are scored
    against the reference's non-matching columns. Columns that already
    match exactly (verbatim) across *every* source are left out of the
    result entirely -- they need no suggestion.

    Parameters
    ----------
    source_columns:
        Mapping of source name -> list of column names as they appear
        in that source. Must have at least 2 sources.
    threshold:
        Minimum similarity score (0-1) for a suggested match to be
        included in the result. Lower catches more real renames but
        raises the false-positive rate -- reasonable to tune per
        dataset. Since nothing here is auto-applied, leaning permissive
        is safe: the caller reviews every suggestion before it's used.

    Returns
    -------
    A mapping of source name -> {original_column: suggested_canonical_name},
    where suggested_canonical_name is the matching column name from the
    reference source. The reference source itself is never a key in the
    result. Nothing here is applied automatically -- the caller reviews
    and opts in via ComparisonSession.apply_column_mapping().
    """
    if len(source_columns) < 2:
        raise ValueError("Need at least 2 sources to suggest a column mapping.")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0 and 1, got {threshold}")

    names = list(source_columns.keys())
    reference_name = names[0]
    reference_columns = source_columns[reference_name]

    # Columns already shared by every source, verbatim, need no suggestion.
    common = set(reference_columns)
    for name in names[1:]:
        common &= set(source_columns[name])

    unmatched_reference = [c for c in reference_columns if c not in common]

    mapping: dict[str, dict[str, str]] = {}
    for name in names[1:]:
        unmatched_here = [c for c in source_columns[name] if c not in common]
        source_mapping = _best_matches(unmatched_here, unmatched_reference, threshold)
        if source_mapping:
            mapping[name] = source_mapping
    return mapping