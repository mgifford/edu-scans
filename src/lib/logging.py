"""Structured logging setup for scan and service workflows."""

from __future__ import annotations

import logging
from typing import Any


class ContextAdapter(logging.LoggerAdapter):
    """Attach structured context fields to log records."""

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        extra = kwargs.get("extra", {})
        merged = {**self.extra, **extra}
        kwargs["extra"] = merged
        return msg, kwargs


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger with stable key/value style output."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s level=%(levelname)s name=%(name)s scan_id=%(scan_id)s country_code=%(country_code)s hostname=%(hostname)s message=%(message)s",
    )


def get_logger(name: str, scan_id: str = "", country_code: str = "", hostname: str = "") -> ContextAdapter:
    """Return a logger adapter with default correlation fields."""
    base = logging.getLogger(name)
    return ContextAdapter(
        base,
        {
            "scan_id": scan_id,
            "country_code": country_code,
            "hostname": hostname,
        },
    )
