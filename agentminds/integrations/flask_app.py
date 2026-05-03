"""Flask integration — registers an error handler + before/after request
hooks so unhandled exceptions, 5xx responses, and request context are
captured automatically.

Usage:
    from flask import Flask
    import agentminds
    from agentminds.integrations.flask_app import init_app

    agentminds.init(dsn="...")
    app = Flask(__name__)
    init_app(app)
"""
from __future__ import annotations
import time

from .. import _hub


def init_app(app) -> None:
    """Wire AgentMinds capture into a Flask app's request lifecycle."""
    try:
        from flask import request, g
    except ImportError:  # pragma: no cover
        raise ImportError("Flask integration requires `flask`. Run: pip install flask")

    @app.before_request
    def _am_before():
        _hub.clear_scope()
        g._am_start = time.monotonic()
        path = request.path
        method = request.method
        _hub.set_transaction(f"{method} {path}")
        _hub.set_tag("http.method", method)
        _hub.set_tag("http.route", path)
        _hub.add_breadcrumb(
            category="http.server",
            message=f"{method} {path}",
            data={"query": str(request.query_string)[:200]} if request.query_string else None,
        )

    @app.errorhandler(Exception)
    def _am_error(exc):
        duration_ms = int((time.monotonic() - getattr(g, "_am_start", time.monotonic())) * 1000)
        _hub.capture_exception(
            exc,
            kind="uncaught",
            http_method=request.method,
            http_path=request.path,
            duration_ms=duration_ms,
        )
        # Re-raise so Flask's normal error handling continues
        raise exc

    @app.after_request
    def _am_after(resp):
        if resp.status_code >= 500:
            duration_ms = int((time.monotonic() - getattr(g, "_am_start", time.monotonic())) * 1000)
            _hub.capture_event({
                "type": "error",
                "fingerprint": f"http_{resp.status_code}_{request.path}",
                "page_url": request.url[:512],
                "payload": {
                    "kind": "http_5xx",
                    "status": resp.status_code,
                    "method": request.method,
                    "path": request.path,
                    "duration_ms": duration_ms,
                    "scope": _hub._scope().to_dict(),
                },
            })
        return resp
