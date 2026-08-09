"""duckdiff: N-way, order-independent comparison of large record files.

Powered by DuckDB for out-of-core streaming, so comparisons can scale
past what fits in memory.
"""

from duckdiff.config import ComparisonConfig, ToleranceRule
from duckdiff.exceptions import ConfigurationError, DuckDiffError, SchemaMismatchError
from duckdiff.results import ComparisonResult, DryRunResult, MismatchSample, SourcePreview, SourceSummary, KeyColumnSuggestion
from duckdiff.session import ComparisonSession

__version__ = "0.1.0"

__all__ = [
    "ComparisonSession",
    "ComparisonConfig",
    "ToleranceRule",
    "ComparisonResult",
    "DryRunResult",
    "KeyColumnSuggestion",
    "SourcePreview",
    "SourceSummary",
    "MismatchSample",
    "DuckDiffError",
    "SchemaMismatchError",
    "ConfigurationError",
]