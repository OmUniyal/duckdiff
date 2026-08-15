# An OOP script with a class, methods, and a top-level function

import logging

logger = logging.getLogger(__name__)
DEFAULT_BATCH_SIZE = 100


class DataProcessor:
    """Processes structured data records."""

    category = "default"

    def __init__(self, batch_size: int = DEFAULT_BATCH_SIZE):
        """Initialise the processor."""
        self.batch_size = batch_size
        self.processed = 0

    def run(self, records: list) -> list:
        """Run processing on a list of records."""
        def _chunk(lst, size):
            """Split list into chunks of given size."""
            for i in range(0, len(lst), size):
                yield lst[i : i + size]

        results = []
        for chunk in _chunk(records, self.batch_size):
            results.extend(self._process_chunk(chunk))
        return results

    def _process_chunk(self, chunk: list) -> list:
        """Process a single chunk of records."""
        self.processed += len(chunk)
        return [r for r in chunk if r is not None]

    @staticmethod
    def validate(record) -> bool:
        """Return True if record is a non-None dict."""
        return record is not None and isinstance(record, dict)


def bootstrap(batch_size: int = DEFAULT_BATCH_SIZE) -> DataProcessor:
    """Create and return a DataProcessor with default settings."""
    logger.info("Bootstrapping DataProcessor")
    return DataProcessor(batch_size=batch_size)