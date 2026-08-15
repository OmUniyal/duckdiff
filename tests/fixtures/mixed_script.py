# Mixed: top-level functions, a class with methods, module statements

import json
from pathlib import Path

OUTPUT_DIR = Path("output")
SUPPORTED_FORMATS = ["csv", "parquet", "json"]


def read_file(path: str) -> dict:
    """Read a JSON file and return its contents."""
    with open(path) as f:
        return json.load(f)


class ReportWriter:
    """Writes comparison reports to disk."""

    default_format = "csv"

    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = output_dir

    def write(self, data: list, fmt: str = "csv") -> Path:
        """Write data to a file in the given format."""
        def _build_path(fmt: str) -> Path:
            """Build the output file path."""
            return self.output_dir / f"report.{fmt}"

        out = _build_path(fmt)
        out.parent.mkdir(parents=True, exist_ok=True)
        return out

    @classmethod
    def supported(cls) -> list:
        """Return list of supported formats."""
        return SUPPORTED_FORMATS


def summarise(results: list) -> str:
    """Return a plain-text summary of results."""
    return f"{len(results)} records processed"


if __name__ == "__main__":
    writer = ReportWriter()
    writer.write([], fmt="csv")