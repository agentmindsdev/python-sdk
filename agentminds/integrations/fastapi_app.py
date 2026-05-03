"""FastAPI integration — captures unhandled exceptions in request handlers,
adds request context (path, method, status), and clears thread-local scope
between requests so users/tags don't bleed across concurrent calls.

Usage:
    from fastapi import FastAPI
    import agentminds
    from agentminds.integrations.fastapi_app import AgentMindsMiddleware

    agentminds.init(dsn="...")
    app = FastAPI()
    app.add_middleware(AgentMindsMiddleware)
"""
from __future__ import annotations
import time

try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
except ImportError:  # pragma: no cover
    raise ImportError(
        "FastAPI integration requires `starlette` (installed with FastAPI). "
        "Run: pip install fastapi"
    )

from .. import _hub


class AgentMindsMiddleware(BaseHTTPMiddleware):
    """Wraps every request to:
      1. Reset thread-local scope (user/tags from prior request don't leak).
      2. Set transaction = "{METHOD} {path}" for correlation.
      3. Add a breadcrumb for the request.
      4. Capture any exception that escapes the handler.
      5. Capture failed responses (>= 500) as error events.
    """

    async def dispatch(self, request: Request, call_next):
        _hub.clear_scope()
        path = request.url.path
        method = request.method
        _hub.set_transaction(f"{method} {path}")
        _hub.set_tag("http.method", method)
        _hub.set_tag("http.route", path)
        _hub.add_breadcrumb(
            category="http.server",
            message=f"{method} {path}",
            data={"query": str(request.url.query)[:200]} if request.url.query else None,
        )
        start = time.monotonic()
        try:
            response: Response = await call_next(request)
        except Exception as exc:
            _hub.capture_exception(
                exc,
                kind="uncaught",
                http_method=method,
                http_path=path,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            raise
        # Capture server errors as events (handler caught + returned 5xx).
        if response.status_code >= 500:
            _hub.capture_event({
                "type": "error",
                "fingerprint": f"http_{response.status_code}_{path}",
                "page_url": str(request.url)[:512],
                "payload": {
                    "kind": "http_5xx",
                    "status": response.status_code,
                    "method": method,
                    "path": path,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "scope": _hub._scope().to_dict(),
                },
            })
        return response
