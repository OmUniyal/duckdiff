"""
AST-based extractor for Python source files.

Parses a .py file into a flat list of DefinitionRows — one row per
function, async function, class, nested function, or module-level
statements block. Designed to feed into ComparisonSession for N-way
structural diffing of Python files.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class DefinitionRow:
    qualified_path: str   # "MyClass.my_method", "top_level_func", "<module_statements>"
    parent_path: str      # "MyClass", "" for top-level
    kind: str             # "function" | "async_function" | "class" | "nested_function" | "module_statements"
    signature_hash: str   # sha256 of args + return annotation; "" for class/module_statements
    body_hash: str        # sha256 of body nodes + docstring
    combined_hash: str    # sha256(signature_hash + ":" + body_hash)
    lineno_start: int     # line of def/class keyword (1-indexed)
    lineno_end: int       # last line of definition body
    decorators: str       # JSON-serialised list of decorator name strings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def file_hash(path: str | Path) -> str:
    """Return a deterministic SHA-256 hash of the entire module AST.

    Insensitive to comments and whitespace — only structural changes
    (added/removed/reordered nodes) will change this hash.
    """
    source = Path(path).read_text(encoding="utf-8")
    if not source.strip():
        return _sha256("")
    tree = ast.parse(source, filename=str(path))
    return _sha256(ast.dump(tree))


def extract_definitions(path: str | Path) -> list[DefinitionRow]:
    """Walk the AST of a Python source file and return one DefinitionRow
    per named definition (function, class, nested function) plus one
    synthetic '<module_statements>' row if any non-definition top-level
    code exists.

    Returns an empty list for an empty file.
    """
    source = Path(path).read_text(encoding="utf-8")
    if not source.strip():
        return []

    tree = ast.parse(source, filename=str(path))
    rows: list[DefinitionRow] = []

    # Separate top-level definitions from module-level statements
    top_def_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    top_defs = [n for n in ast.iter_child_nodes(tree) if isinstance(n, top_def_types)]
    top_stmts = [n for n in ast.iter_child_nodes(tree) if not isinstance(n, top_def_types)]

    # Module-level statements row (imports, assignments, if __name__ == "__main__", etc.)
    if top_stmts:
        stmt_dump = "".join(ast.dump(n) for n in top_stmts)
        bh = _sha256(stmt_dump)
        total_lines = source.count("\n") + 1
        rows.append(
            DefinitionRow(
                qualified_path="<module_statements>",
                parent_path="",
                kind="module_statements",
                signature_hash="",
                body_hash=bh,
                combined_hash=bh,
                lineno_start=1,
                lineno_end=total_lines,
                decorators="[]",
            )
        )

    # Walk top-level definitions
    for node in top_defs:
        rows.extend(_walk_definition(node, parent_path=""))

    return rows


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _walk_definition(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    parent_path: str,
    is_nested_func: bool = False,
) -> list[DefinitionRow]:
    """Recursively emit rows for a definition and all nested definitions."""
    rows: list[DefinitionRow] = []
    name = node.name
    qualified = f"{parent_path}.{name}" if parent_path else name

    if isinstance(node, ast.ClassDef):
        rows.append(_make_class_row(node, qualified, parent_path))
        # Recurse into class body — methods and nested classes
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                rows.extend(_walk_definition(child, parent_path=qualified))

    else:
        # FunctionDef or AsyncFunctionDef
        kind = _func_kind(node, is_nested=is_nested_func)
        rows.append(_make_func_row(node, qualified, parent_path, kind))
        # Recurse into function body — nested functions only
        for child in ast.walk(node):
            if child is node:
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Only direct nested children, not grandchildren
                # (grandchildren will be picked up by their parent's recursion)
                if _is_direct_child_func(child, node):
                    rows.extend(
                        _walk_definition(child, parent_path=qualified, is_nested_func=True)
                    )

    return rows


def _is_direct_child_func(
    candidate: ast.FunctionDef | ast.AsyncFunctionDef,
    parent: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Return True if candidate is a direct nested function of parent,
    not a grandchild (which would be handled by candidate's own recursion)."""
    for node in ast.iter_child_nodes(parent):
        # Direct children of the function body
        for subnode in ast.walk(node):
            if subnode is candidate:
                # Make sure no intermediate FunctionDef sits between parent and candidate
                return _no_intermediate_func(candidate, parent)
    return False


def _no_intermediate_func(
    target: ast.AST,
    root: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Return True if target appears in root's body with no intervening
    FunctionDef/AsyncFunctionDef between them."""
    for child in ast.iter_child_nodes(root):
        if child is target:
            return True
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not target:
            # Target is inside another nested function — not a direct child
            for desc in ast.walk(child):
                if desc is target:
                    return False
    return True


def _make_func_row(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    qualified: str,
    parent_path: str,
    kind: str,
) -> DefinitionRow:
    sig_hash = _hash_signature(node)
    body_hash = _hash_func_body(node)
    return DefinitionRow(
        qualified_path=qualified,
        parent_path=parent_path,
        kind=kind,
        signature_hash=sig_hash,
        body_hash=body_hash,
        combined_hash=_sha256(f"{sig_hash}:{body_hash}"),
        lineno_start=node.lineno,
        lineno_end=node.end_lineno,
        decorators=_serialise_decorators(node),
    )


def _make_class_row(
    node: ast.ClassDef,
    qualified: str,
    parent_path: str,
) -> DefinitionRow:
    # Class body hash: class docstring + class-level assignments only
    # Method bodies are excluded — they appear as their own rows
    class_level_nodes = [
        child for child in ast.iter_child_nodes(node)
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    body_dump = "".join(ast.dump(n) for n in class_level_nodes)
    bh = _sha256(body_dump)
    return DefinitionRow(
        qualified_path=qualified,
        parent_path=parent_path,
        kind="class",
        signature_hash="",
        body_hash=bh,
        combined_hash=bh,
        lineno_start=node.lineno,
        lineno_end=node.end_lineno,
        decorators=_serialise_decorators(node),
    )


def _hash_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Hash arg names, defaults, and return annotation."""
    parts = [ast.dump(node.args)]
    if node.returns is not None:
        parts.append(ast.dump(node.returns))
    return _sha256("".join(parts))


def _hash_func_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Hash the function body including docstring, excluding nested
    function definitions (they get their own rows)."""
    body_nodes = [
        child for child in node.body
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    dump = "".join(ast.dump(n) for n in body_nodes)
    return _sha256(dump)


def _func_kind(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    is_nested: bool,
) -> str:
    if is_nested:
        return "nested_function"
    if isinstance(node, ast.AsyncFunctionDef):
        return "async_function"
    return "function"


def _serialise_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    names: list[str] = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            names.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.append(f"{ast.unparse(dec)}")
        else:
            names.append(ast.unparse(dec))
    return json.dumps(names)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()