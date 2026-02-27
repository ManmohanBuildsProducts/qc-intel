"""Custom exception hierarchy for QC Intel."""


class QCIntelError(Exception):
    """Base exception for all QC Intel errors."""


class ScrapeError(QCIntelError):
    """Error during scraping operations."""

    def __init__(self, platform: str, message: str) -> None:
        self.platform = platform
        super().__init__(f"[{platform}] {message}")


class NormalizationError(QCIntelError):
    """Error during product normalization."""


class AnalyticsError(QCIntelError):
    """Error during analytics/report generation."""


class DatabaseError(QCIntelError):
    """Error during database operations."""


class ConfigError(QCIntelError):
    """Error in configuration or settings."""
