"""Global hub — single Client + per-scope context (user, tags, breadcrumbs).

Sentry-equivalent of `Hub.current` + `Scope`. Thread-local scope so
concurrent requests don't bleed user/tag state into each other.
"""
from __future__ import annotations
import threading
import time
import traceback
from collections import deque
from typing import Any

from ._client import Client


_lock = threading.Lock()
_client: Client | None = None
_thread_local = threading.local()


def set_client(client: Client | None) -> None:
    global _client
    with _lock:
        _client = client


def get_client() -> Client | None:
    return _client


def is_initialized() -> bool:
    return _client is not None


# ────────────────────────────────────────────────────────────────────
# Per-thread scope
# ────────────────────────────────────────────────────────────────────


class _Scope:
    __slots__ = ("user", "tags", "extras", "breadcrumbs", "transaction")

    def __init__(self) -> None:
        self.user: dict | None = None
        self.tags: dict[str, str] = {}
        self.extras: dict[str, Any] = {}
        self.breadcrumbs: deque[dict] = deque(maxlen=100)
        self.transaction: str | None = None

    def to_dict(self) -> dict:
        d: dict = {}
        if self.user:
            d["user"] = self.user
        if self.tags:
            d["tags"] = dict(self.tags)
        if self.extras:
            d["extras"] = dict(self.extras)
        if self.breadcrumbs:
            d["breadcrumbs"] = list(self.breadcrumbs)
        if self.transaction:
            d["transaction"] = self.transaction
        return d


def _scope() -> _Scope:
    s = getattr(_thread_local, "scope", None)
    if s is None:
        s = _Scope()
        _thread_local.scope = s
    return s


def set_user(user: dict | None) -> None:
    _scope().user = user


def set_tag(key: str, value: str) -> None:
    _scope().tags[str(key)[:64]] = str(value)[:200]


def set_extra(key: str, value: Any) -> None:
    _scope().extras[str(key)[:64]] = value


def set_transaction(name: str | None) -> None:
    _scope().transaction = name


def add_breadcrumb(
    *,
    category: str = "default",
    message: str = "",
    level: str = "info",
    data: dict | None = None,
) -> None:
    _scope().breadcrumbs.append({
        "ts": time.time(),
        "category": str(category)[:32],
        "message": str(message)[:500],
        "level": level,
        "data": data or {},
    })


def clear_scope() -> None:
    """Reset thread-local scope — call between requests in a worker pool."""
    _thread_local.scope = _Scope()


# ────────────────────────────────────────────────────────────────────
# Capture
# ────────────────────────────────────────────────────────────────────


def _fingerprint(*parts: str) -> str:
    """djb2 hash → base36 — same shape as agent.js fingerprints."""
    h = 5381
    for p in parts:
        for ch in str(p):
            h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return f"{h:x}"


def capture_exception(exc: BaseException | None = None, **extra) -> None:
    client = get_client()
    if client is None:
        return
    if exc is None:
        import sys as _sys
        exc_info = _sys.exc_info()
        if exc_info[0] is None:
            return
        exc_type, exc, tb = exc_info
    else:
        exc_type = type(exc)
        tb = exc.__traceback__

    stack = "".join(traceback.format_exception(exc_type, exc, tb))[:8000]
    msg = f"{exc_type.__name__}: {exc}"[:500]
    src = ""
    line = 0
    if tb:
        # Walk to the deepest frame (where the exception was raised)
        last = tb
        while last.tb_next is not None:
            last = last.tb_next
        src = (last.tb_frame.f_code.co_filename or "")[:300]
        line = last.tb_lineno or 0

    event = {
        "type": "error",
        "fingerprint": _fingerprint(exc_type.__name__, src, str(line)),
        "payload": {
            "kind": "uncaught" if extra.get("kind") == "uncaught" else "captured",
            "message": msg,
            "exception_type": exc_type.__name__,
            "source": src,
            "line": line,
            "stack": stack,
            **{k: v for k, v in extra.items() if k != "kind"},
            "scope": _scope().to_dict(),
        },
    }
    client.enqueue(event)


def capture_message(
    message: str,
    level: str = "info",
    **extra,
) -> None:
    client = get_client()
    if client is None:
        return
    event = {
        "type": "custom" if level == "info" else "error",
        "fingerprint": _fingerprint("msg", message[:64], level),
        "payload": {
            "kind": "message",
            "level": level,
            "message": str(message)[:1000],
            **extra,
            "scope": _scope().to_dict(),
        },
    }
    client.enqueue(event)


def capture_event(event: dict) -> None:
    """Low-level — bypass scope wrapping for fully-formed events."""
    client = get_client()
    if client is not None:
        client.enqueue(event)
