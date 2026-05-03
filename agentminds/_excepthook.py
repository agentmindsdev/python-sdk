"""Hook sys.excepthook + threading.excepthook so any uncaught exception
in any thread surfaces in AgentMinds.

We chain to whatever hook was already installed (debugger, IDE, prior
SDK) instead of replacing it — calling our handler last keeps original
behavior intact (exception still prints to stderr, IDE still pauses).
"""
from __future__ import annotations
import sys
import threading

from . import _hub

_original_excepthook = None
_original_thread_excepthook = None
_installed = False


def install() -> None:
    global _original_excepthook, _original_thread_excepthook, _installed
    if _installed:
        return
    _original_excepthook = sys.excepthook
    sys.excepthook = _agentminds_excepthook

    # threading.excepthook landed in Python 3.8.
    if hasattr(threading, "excepthook"):
        _original_thread_excepthook = threading.excepthook
        threading.excepthook = _agentminds_thread_excepthook

    _installed = True


def _agentminds_excepthook(exc_type, exc, tb) -> None:
    try:
        if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            exc.__traceback__ = tb
            _hub.capture_exception(exc, kind="uncaught")
            client = _hub.get_client()
            if client is not None:
                client.flush(timeout=2.0)
    except Exception:
        # Never swallow the original exception because of our hook.
        pass
    finally:
        if _original_excepthook is not None:
            _original_excepthook(exc_type, exc, tb)


def _agentminds_thread_excepthook(args) -> None:
    try:
        if args.exc_type is not None and not issubclass(
            args.exc_type, (KeyboardInterrupt, SystemExit)
        ):
            if args.exc_value is not None:
                args.exc_value.__traceback__ = args.exc_traceback
                _hub.capture_exception(args.exc_value, kind="uncaught", thread=getattr(args.thread, "name", "?"))
    except Exception:
        pass
    finally:
        if _original_thread_excepthook is not None:
            _original_thread_excepthook(args)
