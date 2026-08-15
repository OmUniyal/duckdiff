"""
PythonFileSession — thin session wrapper for N-way Python file comparison.

Accepts N .py file paths, runs a two-phase comparison:
  Phase A: file-level hash check (fast early exit if all files identical)
  Phase B: definition-level drill-down via AST extraction

Returns a PythonComparisonResult. Does not touch ComparisonSession or
comparator.py — the AST extractor feeds this session directly.
"""

from __future__ import annotations

from pathlib import Path

from duckdiff.exceptions import ConfigurationError, DuckDiffError
from duckdiff.extractors.python_ast import DefinitionRow, extract_definitions, file_hash
from duckdiff.results import DefinitionDiff, PythonComparisonResult


class PythonFileSession:
    """N-way structural comparison of Python source files via AST extraction."""

    def __init__(self) -> None:
        self._sources: dict[str, Path] = {}  # label → resolved path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_source(self, label: str, path: str | Path) -> None:
        """Register a .py file under a short label (e.g. 'a', 'b').

        Raises:
            ConfigurationError: if label is already registered.
            DuckDiffError: if path does not exist or is not a .py file.
        """
        if label in self._sources:
            raise ConfigurationError(f"Label {label!r} is already registered.")

        resolved = Path(path)
        if not resolved.exists():
            raise DuckDiffError(f"Path does not exist: {resolved}")
        if resolved.suffix != ".py":
            raise DuckDiffError(f"Expected a .py file, got: {resolved.name}")

        self._sources[label] = resolved

    def compare(self) -> PythonComparisonResult:
        """Run the two-phase comparison across all registered sources.

        Raises:
            ConfigurationError: if fewer than 2 sources are registered.
        """
        if len(self._sources) < 2:
            raise ConfigurationError(
                f"At least 2 sources required, got {len(self._sources)}."
            )

        labels = list(self._sources.keys())
        paths = self._sources

        # ── Phase A: file hash check ──────────────────────────────────
        hashes = {label: file_hash(paths[label]) for label in labels}
        sources_str = {label: str(paths[label]) for label in labels}

        if len(set(hashes.values())) == 1:
            return PythonComparisonResult(
                sources=sources_str,
                files_identical=True,
                file_hashes=hashes,
                definitions=[],
            )

        # ── Phase B: definition drill-down ────────────────────────────
        extracted: dict[str, dict[str, DefinitionRow]] = {
            label: {row.qualified_path: row for row in extract_definitions(paths[label])}
            for label in labels
        }

        # Union of all qualified_paths across all sources
        all_paths: set[str] = set()
        for rows_by_path in extracted.values():
            all_paths.update(rows_by_path.keys())

        diffs: list[DefinitionDiff] = []

        for qpath in sorted(all_paths):
            present_in_labels = [l for l in labels if qpath in extracted[l]]
            missing_in_labels = [l for l in labels if qpath not in extracted[l]]

            if missing_in_labels:
                # Definition exists in some sources but not all
                representative = extracted[present_in_labels[0]][qpath]
                diffs.append(
                    DefinitionDiff(
                        qualified_path=qpath,
                        parent_path=representative.parent_path,
                        kind=representative.kind,
                        status="missing",
                        lineno_start=representative.lineno_start,
                        lineno_end=representative.lineno_end,
                        decorators=representative.decorators,
                        present_in=", ".join(present_in_labels),
                    )
                )
                continue

            # Definition present in all sources — compare hashes
            combined_hashes = {l: extracted[l][qpath].combined_hash for l in labels}
            sig_hashes = {l: extracted[l][qpath].signature_hash for l in labels}
            body_hashes = {l: extracted[l][qpath].body_hash for l in labels}

            # Use the first source as representative for line numbers/decorators
            representative = extracted[labels[0]][qpath]

            if len(set(combined_hashes.values())) == 1:
                diffs.append(
                    DefinitionDiff(
                        qualified_path=qpath,
                        parent_path=representative.parent_path,
                        kind=representative.kind,
                        status="unchanged",
                        lineno_start=representative.lineno_start,
                        lineno_end=representative.lineno_end,
                        decorators=representative.decorators,
                    )
                )
            else:
                sig_changed = len(set(sig_hashes.values())) > 1
                body_changed = len(set(body_hashes.values())) > 1
                diffs.append(
                    DefinitionDiff(
                        qualified_path=qpath,
                        parent_path=representative.parent_path,
                        kind=representative.kind,
                        status="changed",
                        lineno_start=representative.lineno_start,
                        lineno_end=representative.lineno_end,
                        decorators=representative.decorators,
                        signature_changed=sig_changed,
                        body_changed=body_changed,
                    )
                )

        # ── Compute counts ────────────────────────────────────────────
        changed = sum(1 for d in diffs if d.status == "changed")
        unchanged = sum(1 for d in diffs if d.status == "unchanged")
        missing = sum(1 for d in diffs if d.status == "missing")

        order_only = (
            changed == 0
            and missing == 0
            and unchanged > 0
        )

        return PythonComparisonResult(
            sources=sources_str,
            files_identical=False,
            file_hashes=hashes,
            definitions=diffs,
            changed=changed,
            unchanged=unchanged,
            missing=missing,
            order_only=order_only,
        )