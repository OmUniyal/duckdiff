# A plain script with no classes — only top-level functions and module statements

import os
import sys

BASE_DIR = os.path.dirname(__file__)
MAX_RETRIES = 3


def load_config(path: str) -> dict:
    """Load configuration from a file path."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path) as f:
        return {"path": path, "content": f.read()}


def process_records(records: list, retries: int = MAX_RETRIES) -> list:
    """Process a list of records with retry logic."""
    def _validate(record):
        """Validate a single record."""
        return record is not None and isinstance(record, dict)

    results = []
    for record in records:
        if _validate(record):
            results.append(record)
    return results


def main():
    config = load_config("config.json")
    data = process_records([{"a": 1}, None, {"b": 2}])
    print(config, data)


if __name__ == "__main__":
    main()