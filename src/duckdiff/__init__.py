"""duckdiff: N-way, order-independent comparison of large record files
and Python source files.

Powered by DuckDB for out-of-core streaming, so comparisons can scale
past what fits in memory.
"""

from duckdiff.config import ComparisonConfig, ToleranceRule
from duckdiff.exceptions import ConfigurationError, DuckDiffError, SchemaMismatchError
from duckdiff.python_file_session import PythonFileSession
from duckdiff.results import (
    ComparisonResult,
    DefinitionDiff,
    DryRunResult,
    KeyColumnSuggestion,
    MismatchSample,
    PythonComparisonResult,
    SourcePreview,
    SourceSummary,
)
from duckdiff.session import ComparisonSession

__version__ = "0.2.0"

__all__ = [
    # Structured data comparison
    "ComparisonSession",
    "ComparisonConfig",
    "ToleranceRule",
    "ComparisonResult",
    "DryRunResult",
    "KeyColumnSuggestion",
    "SourcePreview",
    "SourceSummary",
    "MismatchSample",
    # Python file comparison
    "PythonFileSession",
    "PythonComparisonResult",
    "DefinitionDiff",
    # Exceptions
    "DuckDiffError",
    "SchemaMismatchError",
    "ConfigurationError",
]