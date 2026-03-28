"""Python class with self.method() calls for testing."""

import logging


class RecordProcessor:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.batch = []

    def process(self, record):
        validated = self._validate_record(record)
        if validated:
            self._add_to_batch(validated)
            if len(self.batch) >= self.config.batch_size:
                self._flush_batch()

    def _validate_record(self, record):
        if not record.get("id"):
            self.logger.warning("Missing ID")
            return None
        return record

    def _add_to_batch(self, record):
        self.batch.append(record)

    def _flush_batch(self):
        self._retry_failed(self.batch)
        self.batch = []

    def _retry_failed(self, items):
        for item in items:
            self.logger.debug("Retrying %s", item["id"])
