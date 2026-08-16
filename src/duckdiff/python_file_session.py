"""
PythonFileSession — thin session wrapper for N-way Python file comparison.

Accepts N .py file paths, runs a two-phase comparison:
  Phase A: file-level hash check (fast early exit if all files identical)
  Phase B: definition-level drill-down via AST extraction

Returns a PythonComparisonResult. Does not touch ComparisonSession or
comparator.py — the AST extractor feeds this session directly.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from duckdiff.exceptions import ConfigurationError, DuckDiffError
from duckdiff.extractors.python_ast import DefinitionRow, extract_definitions, file_hash
from duckdiff.results import DefinitionDiff, PythonComparisonResult

_FUZZY_THRESHOLD = 0.6


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

    def suggest_path_mapping(self) -> dict[str, str]:
        """Suggest likely renames across exactly 2 registered sources.

        Compares qualified_paths that are 'missing' in each source and
        returns a mapping of old_path → new_path for pairs that score
        above the similarity threshold. Only paths of the same kind are
        matched. Never auto-applied — always explicit human opt-in.

        Raises:
            ConfigurationError: if not exactly 2 sources are registered.
        """
        if len(self._sources) != 2:
            raise ConfigurationError(
                "suggest_path_mapping() requires exactly 2 sources, "
                f"got {len(self._sources)}. Fuzzy path matching is not "
                "supported for N-way (3+) comparisons."
            )

        result = self.compare()
        if result.files_identical:
            return {}

        missing_defs = [d for d in result.definitions if d.status == "missing"]
        if not missing_defs:
            return {}

        labels = list(self._sources.keys())
        label_a, label_b = labels[0], labels[1]

        # Split missing defs by which source they're present in
        only_in_a = [d for d in missing_defs if label_a in d.present_in.split(", ")]
        only_in_b = [d for d in missing_defs if label_b in d.present_in.split(", ")]

        suggestions: dict[str, str] = {}
        used_targets: set[str] = set()

        for candidate in only_in_a:
            best_score = 0.0
            best_match: DefinitionDiff | None = None

            for target in only_in_b:
                # Only match same kind
                if target.kind != candidate.kind:
                    continue
                if target.qualified_path in used_targets:
                    continue
                score = SequenceMatcher(
                    None,
                    candidate.qualified_path,
                    target.qualified_path,
                ).ratio()
                if score > best_score:
                    best_score = score
                    best_match = target

            if best_match is not None and best_score >= _FUZZY_THRESHOLD:
                suggestions[candidate.qualified_path] = best_match.qualified_path
                used_targets.add(best_match.qualified_path)

        return suggestions

    def apply_path_mapping(self, mapping: dict[str, str]) -> PythonComparisonResult:
        """Rerun the comparison treating old_path → new_path as renames.

        Definitions matched by the mapping get status='renamed' instead
        of appearing as two separate 'missing' entries. Body and signature
        change flags are still populated for renamed definitions.

        Args:
            mapping: dict of old_qualified_path → new_qualified_path,
                     as returned by suggest_path_mapping().

        Raises:
            ConfigurationError: if not exactly 2 sources are registered.
        """
        if len(self._sources) != 2:
            raise ConfigurationError(
                "apply_path_mapping() requires exactly 2 sources."
            )

        result = self.compare()
        if result.files_identical:
            return result

        labels = list(self._sources.keys())
        extracted: dict[str, dict[str, DefinitionRow]] = {
            label: {
                row.qualified_path: row
                for row in extract_definitions(self._sources[label])
            }
            for label in labels
        }

        # Paths that are consumed by the mapping (excluded from missing)
        mapped_old = set(mapping.keys())
        mapped_new = set(mapping.values())

        new_defs: list[DefinitionDiff] = []

        for d in result.definitions:
            if d.status != "missing":
                new_defs.append(d)
                continue
            if d.qualified_path in mapped_old or d.qualified_path in mapped_new:
                continue  # will be replaced by a renamed entry below
            new_defs.append(d)

        # Build renamed entries
        label_a, label_b = labels[0], labels[1]
        for old_path, new_path in mapping.items():
            row_a = extracted[label_a].get(old_path)
            row_b = extracted[label_b].get(new_path)
            if row_a is None or row_b is None:
                continue  # mapping references unknown path — skip silently

            sig_changed = row_a.signature_hash != row_b.signature_hash
            body_changed = row_a.body_hash != row_b.body_hash

            new_defs.append(
                DefinitionDiff(
                    qualified_path=new_path,
                    parent_path=row_b.parent_path,
                    kind=row_b.kind,
                    status="renamed",
                    lineno_start=row_b.lineno_start,
                    lineno_end=row_b.lineno_end,
                    decorators=row_b.decorators,
                    signature_changed=sig_changed,
                    body_changed=body_changed,
                    renamed_from=old_path,
                )
            )

        # Sort: changed, renamed, missing, unchanged
        _order = {"changed": 0, "renamed": 1, "missing": 2, "unchanged": 3}
        new_defs.sort(key=lambda d: (_order.get(d.status, 9), d.qualified_path))

        changed = sum(1 for d in new_defs if d.status == "changed")
        unchanged = sum(1 for d in new_defs if d.status == "unchanged")
        missing = sum(1 for d in new_defs if d.status == "missing")
        renamed = sum(1 for d in new_defs if d.status == "renamed")
        order_only = changed == 0 and missing == 0 and renamed == 0 and unchanged > 0

        return PythonComparisonResult(
            sources=result.sources,
            files_identical=False,
            file_hashes=result.file_hashes,
            definitions=new_defs,
            changed=changed,
            unchanged=unchanged,
            missing=missing,
            renamed=renamed,
            order_only=order_only,
        )

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