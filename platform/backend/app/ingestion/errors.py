"""Exceptions raised by the ingestion pipeline."""


class IngestionError(Exception):
    """Base class for all ingestion errors."""


class MappingError(IngestionError):
    """A raw Sportmonks payload could not be mapped to our schema (missing
    required fields, unparseable values, etc.)."""


class LeakageError(IngestionError):
    """Refused to store a row because it cannot be proven the data was
    known before the fixture's kickoff."""
