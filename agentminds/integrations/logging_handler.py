"""Logging integration — forwards ERROR-and-above logs to AgentMinds and
adds INFO/WARNING logs as breadcrumbs (so they show up as context on the
next captured event).

Usage:
    import logging, agentminds
    from agentminds.integrations.logging_handler import attach

    agentminds.init(dsn="...")
    attach()  # adds handler to root logger

    logging.error("something broke", extra={"order_id": 42})
"""
from __future__ import annotations
import logging

from .. import _hub


class AgentMindsLogHandler(logging.Handler):
    """Forward records → capture_message (or capture_exception if exc_info)."""

    def __init__(self, level: int = logging.WARNING, breadcrumb_level: int = logging.INFO):
        super().__init__(level=breadcrumb_level)
        # Capture as event for >= `level`; everything between
        # `breadcrumb_level` and `level` becomes a breadcrumb.
        self._event_level = level

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            if record.name.startswith("agentminds"):
                return  # don't loop our own debug logs back
            if record.levelno < self._event_level:
                _hub.add_breadcrumb(
                    category=f"log.{record.name}",
                    message=record.getMessage()[:500],
                    level=record.levelname.lower(),
                )
                return

            extras = {
                "logger": record.name,
                "level": record.levelname,
                "module": record.module,
                "func": record.funcName,
                "line": record.lineno,
            }
            if record.exc_info and record.exc_info[1]:
                exc = record.exc_info[1]
                exc.__traceback__ = record.exc_info[2]
                _hub.capture_exception(exc, **extras, log_message=record.getMessage()[:500])
            else:
                _hub.capture_message(
                    record.getMessage(),
                    level=record.levelname.lower(),
                    **extras,
                )
        except Exception:
            self.handleError(record)


def attach(
    level: int = logging.WARNING,
    breadcrumb_level: int = logging.INFO,
    logger: str | logging.Logger | None = None,
) -> AgentMindsLogHandler:
    """Attach the handler to a logger (root by default).

    Returns the handler so the caller can later detach() if needed.
    """
    target = (
        logging.getLogger(logger)
        if isinstance(logger, str) or logger is None
        else logger
    )
    handler = AgentMindsLogHandler(level=level, breadcrumb_level=breadcrumb_level)
    target.addHandler(handler)
    return handler
