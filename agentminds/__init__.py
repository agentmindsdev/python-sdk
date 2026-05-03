"""AgentMinds — Python SDK.

Sentry-style auto-capture for Python web apps. One `init()` call hooks
sys.excepthook, threading.excepthook, and (when integrations="auto")
your web framework's error pipeline. Uncaught exceptions, 5xx responses,
and ERROR-level logs ship to AgentMinds in the background; manual capture
APIs (`capture_exception`, `capture_message`, breadcrumbs, scope) are
available for places that catch + handle errors locally.

Quickstart:
    import agentminds
    agentminds.init(dsn="https://pk_yoursite_xxx@api.agentminds.dev/yoursite")

    # FastAPI
    from agentminds.integrations.fastapi_app import AgentMindsMiddleware
    app.add_middleware(AgentMindsMiddleware)

    # Flask
    from agentminds.integrations.flask_app import init_app
    init_app(app)

    # Logging
    from agentminds.integrations.logging_handler import attach
    attach()
"""
from __future__ import annotations
import logging
from typing import Any

from . import _excepthook, _hub
from . import sync  # high-level /sync/* API client (push reports, pull recs)
from ._client import client_from_env, Client
from ._dsn import DSN, InvalidDSN
from ._hub import (
    add_breadcrumb,
    capture_event,
    capture_exception,
    capture_message,
    clear_scope,
    get_client,
    is_initialized,
    set_extra,
    set_tag,
    set_transaction,
    set_user,
)

__version__ = "0.5.0"

__all__ = [
    "init",
    "flush",
    "close",
    "capture_exception",
    "capture_message",
    "capture_event",
    "set_user",
    "set_tag",
    "set_extra",
    "set_transaction",
    "add_breadcrumb",
    "clear_scope",
    "is_initialized",
    "get_client",
    "sync",
    "DSN",
    "InvalidDSN",
    "__version__",
]

log = logging.getLogger("agentminds")


def init(
    dsn: str | None = None,
    *,
    release: str | None = None,
    environment: str | None = None,
    sample_rate: float = 1.0,
    debug: bool = False,
    send_default_pii: bool = False,
    integrations: str | list[str] = "auto",
    install_excepthook: bool = True,
    attach_logging: bool = True,
    logging_level: int = logging.ERROR,
    breadcrumb_level: int = logging.INFO,
    introspect_code: bool = True,
    project_root: str | None = None,
) -> Client | None:
    """Initialise the SDK. Idempotent — second call replaces the prior client.

    Args:
        dsn: ``https://pk_xxx@api.agentminds.dev/site_id``. Falls back to
            ``$AGENTMINDS_DSN`` if omitted. If neither is set, init returns
            None silently — the SDK becomes a no-op so dev environments don't
            need a DSN.
        release: Build identifier ("v1.2.3", git sha). Auto-detected from
            ``git rev-parse --short HEAD`` when omitted.
        environment: "production" / "staging" / "dev". Defaults to "production".
        sample_rate: Drop fraction of events to control volume (0.0–1.0).
        debug: Log SDK internals to the "agentminds" logger at DEBUG level.
        send_default_pii: Allow sending request bodies / user emails. Off
            by default to avoid leaking PII to the central server.
        integrations: "auto" runs framework auto-detection; pass [] to
            disable; pass ["fastapi"] etc. to opt in to specific ones.
        install_excepthook: Hook ``sys.excepthook`` + ``threading.excepthook``.
        attach_logging: Attach a logging handler to the root logger.
        logging_level: Forward logs at this level and above as events
            (default: ERROR). Lower levels become breadcrumbs.
        breadcrumb_level: Capture logs at this level and above as breadcrumbs
            (default: INFO).

    Returns:
        The initialised :class:`Client`, or ``None`` if no DSN was provided.
    """
    client = client_from_env(
        dsn=dsn,
        release=release,
        environment=environment,
        sample_rate=sample_rate,
        debug=debug,
        send_default_pii=send_default_pii,
    )
    if client is None:
        if debug:
            log.debug("agentminds.init(): no DSN — SDK is a no-op")
        _hub.set_client(None)
        return None

    _hub.set_client(client)

    if install_excepthook:
        _excepthook.install()

    if attach_logging:
        from .integrations.logging_handler import attach
        attach(level=logging_level, breadcrumb_level=breadcrumb_level)

    if integrations == "auto" or (isinstance(integrations, list) and integrations):
        _auto_attach_frameworks(integrations)

    # Code introspection — walk the host app's codebase ONCE at startup
    # and ship a structured "code signature" so AgentMinds knows the
    # shape of what it's monitoring (frameworks, routes, decorator
    # patterns, third-party deps) without the user having to do anything
    # extra. Best-effort, time-capped, never raises out.
    if introspect_code:
        try:
            from ._introspect import push_code_signature
            sig_hash = push_code_signature(client, root=project_root)
            if debug and sig_hash:
                log.debug("agentminds: code signature shipped — hash=%s", sig_hash)
        except Exception as e:
            if debug:
                log.debug("agentminds: introspection skipped — %s", e)

    if debug:
        log.debug(
            "agentminds.init() OK — site=%s release=%s env=%s",
            client.dsn.site_id, client.release, client.environment,
        )

    return client


def flush(timeout: float = 2.0) -> bool:
    """Block until in-flight events ship or `timeout` elapses.

    Useful before a serverless handler returns or a CLI script exits.
    """
    client = _hub.get_client()
    return client.flush(timeout=timeout) if client else True


def close() -> None:
    """Stop the worker thread and flush. Subsequent capture calls become
    no-ops until ``init()`` is called again.
    """
    client = _hub.get_client()
    if client is not None:
        client.close()
        _hub.set_client(None)


def _auto_attach_frameworks(integrations: str | list[str]) -> None:
    """Best-effort: import-detect frameworks already in sys.modules and
    register hooks the user didn't manually wire up. We do NOT import
    frameworks the user hasn't installed (would slow down cold start).
    """
    import sys
    enabled: set[str] = set()
    if isinstance(integrations, list):
        enabled = {s.lower() for s in integrations}
        explicit = True
    else:
        # auto: only attach if framework is already imported
        explicit = False

    if (explicit and "fastapi" in enabled) or (not explicit and "fastapi" in sys.modules):
        try:
            # Don't auto-add middleware (we don't have the app instance);
            # users still call `app.add_middleware(AgentMindsMiddleware)`.
            # Importing here just ensures the module loads cleanly so
            # the user gets an early error if starlette is missing.
            from .integrations import fastapi_app  # noqa: F401
        except Exception as e:
            if log.isEnabledFor(logging.DEBUG):
                log.debug("fastapi integration skipped: %s", e)

    if (explicit and "flask" in enabled) or (not explicit and "flask" in sys.modules):
        try:
            from .integrations import flask_app  # noqa: F401
        except Exception as e:
            if log.isEnabledFor(logging.DEBUG):
                log.debug("flask integration skipped: %s", e)
