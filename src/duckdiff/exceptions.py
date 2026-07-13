"""Custom exceptions for duckdiff."""

from __future__ import annotations


class DuckDiffError(Exception):
    """Base exception for all duckdiff errors."""


class SchemaMismatchError(DuckDiffError):
    """Raised when sources have incompatible schemas and no mapping was supplied."""


class ConfigurationError(DuckDiffError):
    """Raised when a ComparisonConfig is invalid or internally inconsistent."""
