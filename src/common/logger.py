"""
Structured logging system for the Plex media tool.

This module provides a centralized logging system with JSON formatting,
multiple log levels, and file rotation capabilities.
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON."""
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
                "exc_info",
                "exc_text",
                "stack_info",
            }:
                log_entry[key] = value

        return json.dumps(log_entry)


class PlexLogger:
    """Centralized logger for the Plex media tool."""

    def __init__(
            self,
            name: str = "plex-media-tool",
            log_level: str = "INFO",
            log_dir: Optional[Path] = None,
            enable_console: bool = True,
    ):
        """
        Initialize the logger.

        Args:
            name: Logger name
            log_level: Log level (DEBUG, INFO, WARN, ERROR)
            log_dir: Directory for log files, default is ./.logs
            enable_console: Whether to enable console output

        Note:
            Each run creates a new timestamped log file (e.g., plex-media-tool_20260119_005448.log)
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper()))

        # Clear any existing handlers
        self.logger.handlers.clear()

        # Set up console handler if enabled
        if enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)

        # Set up file handler with timestamped filename
        log_dir = log_dir or Path.cwd() / ".logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"{name}_{timestamp}.log"

        file_handler = logging.FileHandler(
            log_file,
            mode="w",  # Write mode - creates new file each time
            encoding="utf-8",
        )
        file_formatter = JSONFormatter()
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

    def debug(self, message: str, **kwargs) -> None:
        """Log a debug message."""
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        """Log an info message."""
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        """Log a warning message."""
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        """Log an error message."""
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        """Log a critical message."""
        self._log(logging.CRITICAL, message, **kwargs)

    def _log(self, level: int, message: str, **kwargs) -> None:
        """Internal logging method with extra fields."""
        extra = {}
        for key, value in kwargs.items():
            if key not in {"exc_info", "stack_info"}:
                extra[key] = value

        self.logger.log(level, message, extra=extra)

    def log_file_operation(
            self,
            operation: str,
            source_path: Path,
            destination_path: Optional[Path] = None,
            success: bool = True,
            error_message: Optional[str] = None,
    ) -> None:
        """Log a file operation with structured data."""
        log_data = {
            "operation": operation,
            "source_path": str(source_path),
            "success": success,
        }

        if destination_path:
            log_data["destination_path"] = str(destination_path)

        if error_message:
            log_data["error"] = error_message

        if success:
            self.info(f"File operation completed: {operation}", **log_data)
        else:
            self.error(f"File operation failed: {operation}", **log_data)

    def log_tmdb_request(
            self,
            request_type: str,
            query: str,
            success: bool,
            result_count: Optional[int] = None,
            tmdb_id: Optional[int] = None,
            error_message: Optional[str] = None,
    ) -> None:
        """Log a TMDb API request."""
        log_data = {
            "request_type": request_type,
            "query": query,
            "success": success,
        }

        if result_count is not None:
            log_data["result_count"] = str(result_count)

        if tmdb_id is not None:
            log_data["tmdb_id"] = str(tmdb_id)

        if error_message:
            log_data["error"] = error_message

        if success:
            self.info(f"TMDb request completed: {request_type}", **log_data)
        else:
            self.error(f"TMDb request failed: {request_type}", **log_data)

    def log_processing_step(
            self,
            step: str,
            filepath: Path,
            content_type: str,
            success: bool,
            details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a processing step for a file."""
        log_data = {
            "step": step,
            "filepath": str(filepath),
            "content_type": content_type,
            "success": success,
        }

        if details:
            log_data.update(details)

        if success:
            self.info(f"Processing step completed: {step}", **log_data)
        else:
            self.error(f"Processing step failed: {step}", **log_data)


# Global logger instance
_global_logger: Optional[PlexLogger] = None


def setup_logging(
        log_level: str = "INFO",
        log_dir: Optional[Path] = None,
        enable_console: bool = True,
) -> PlexLogger:
    """Set up the global logging system."""
    global _global_logger

    if log_dir is None:
        log_dir = Path.cwd() / ".logs"

    _global_logger = PlexLogger(
        log_level=log_level,
        log_dir=log_dir,
        enable_console=enable_console,
    )

    return _global_logger


def get_logger() -> PlexLogger:
    """Get the global logger instance."""
    global _global_logger
    if _global_logger is None:
        # Set up default logging if not already configured
        _global_logger = setup_logging()

    return _global_logger


# Convenience functions that use the global logger
def debug(message: str, **kwargs) -> None:
    """Log a debug message using the global logger."""
    get_logger().debug(message, **kwargs)


def info(message: str, **kwargs) -> None:
    """Log an info message using the global logger."""
    get_logger().info(message, **kwargs)


def warning(message: str, **kwargs) -> None:
    """Log a warning message using the global logger."""
    get_logger().warning(message, **kwargs)


def error(message: str, **kwargs) -> None:
    """Log an error message using the global logger."""
    get_logger().error(message, **kwargs)


def critical(message: str, **kwargs) -> None:
    """Log a critical message using the global logger."""
    get_logger().critical(message, **kwargs)
