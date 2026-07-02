class YtDownloadError(Exception):
    """Base exception class for all YouTube Downloader errors."""
    pass


class DownloaderConfigurationError(YtDownloadError):
    """Raised when there is an issue with the application configurations."""
    pass


class TaskNotFoundError(YtDownloadError):
    """Raised when a requested download task is not found in the queue."""
    pass


class MetadataExportError(YtDownloadError):
    """Raised when metadata extraction or CSV logging fails."""
    pass


class NotificationError(YtDownloadError):
    """Raised when sending Telegram telemetry notifications fails."""
    pass
