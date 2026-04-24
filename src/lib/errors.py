"""Custom error types for configuration, ingestion, and storage flows."""

class AppError(Exception):
    """Base application error."""


class ConfigError(AppError):
    """Invalid or missing runtime configuration."""


class IngestionError(AppError):
    """Raised when source ingestion fails validation."""


class StorageError(AppError):
    """Raised when persistence operations fail."""
