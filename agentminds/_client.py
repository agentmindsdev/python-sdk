"""HTTP client — background worker thread + batched send.

Mirrors agent.js wire format so the same /sync/ingest endpoint accepts both
browser and server events. Stdlib only (urllib.request) — no external deps.

Design:
  * Capture-side (any thread, any signal handler): cheap enqueue, never block.
  * Worker thread: drains queue every FLUSH_INTERVAL_S or when queue >=
    FLUSH_THRESHOLD; POSTs JSON; drops on persistent failure rather than
    growing unbounded.
  * atexit hook: forces a final flush so events queued during interpreter
    shutdown still ship (best-effort, bounded by SHUTDOWN_TIMEOUT_S).
"""
from __future__ import annotations
import json
import logging
import os
import queue
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from ._dsn import DSN

log = logging.getLogger("agentminds")

FLUSH_INTERVAL_S = 5.0
FLUSH_THRESHOLD = 30
MAX_QUEUE = 1000
SHUTDOWN_TIMEOUT_S = 3.0
HTTP_TIMEOUT_S = 8.0


class Client:
    """Singleton-per-init transport. Owns the worker thread and queue."""

    def __init__(
        self,
        dsn: DSN,
        release: str | None = None,
        environment: str | None = None,
        sample_rate: float = 1.0,
        debug: bool = False,
        send_default_pii: bool = False,
    ):
        self.dsn = dsn
        self.release = release
        self.environment = environment or "production"
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self.debug = debug
        self.send_default_pii = send_default_pii

        self._queue: queue.Queue = queue.Queue(maxsize=MAX_QUEUE)
        self._stop = threading.Event()
        self._hostname = socket.gethostname()
        self._runtime = f"python/{sys.version_info[0]}.{sys.version_info[1]}"
        self._worker = threading.Thread(
            target=self._run, name="agentminds-worker", daemon=True
        )
        self._worker.start()

        # Final flush on interpreter shutdown
        import atexit
        atexit.register(self.close)

    # ────────────────────────────────────────────────────────
    # Capture API — called from any thread
    # ────────────────────────────────────────────────────────

    def enqueue(self, event: dict[str, Any]) -> None:
        if self.sample_rate < 1.0:
            import random
            if random.random() > self.sample_rate:
                return
        # Stamp common metadata once on the producer side so the worker
        # can ship it as-is.
        event.setdefault("payload", {})
        meta = event["payload"].setdefault("meta", {})
        meta.setdefault("hostname", self._hostname)
        meta.setdefault("runtime", self._runtime)
        if self.environment:
            meta.setdefault("environment", self.environment)
        if self.release:
            meta.setdefault("release", self.release)

        try:
            self._queue.put_nowait(event)
        except queue.Full:
            # Drop oldest to make room — back-pressure should never crash the app.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except Exception:
                pass

    # ────────────────────────────────────────────────────────
    # Worker loop
    # ────────────────────────────────────────────────────────

    def _run(self) -> None:
        batch: list[dict] = []
        last_flush = time.monotonic()
        while not self._stop.is_set():
            try:
                timeout = max(0.1, FLUSH_INTERVAL_S - (time.monotonic() - last_flush))
                ev = self._queue.get(timeout=timeout)
                batch.append(ev)
            except queue.Empty:
                pass

            now = time.monotonic()
            should_flush = (
                len(batch) >= FLUSH_THRESHOLD
                or (batch and (now - last_flush) >= FLUSH_INTERVAL_S)
            )
            if should_flush:
                self._send(batch)
                batch = []
                last_flush = now

        # Drain on shutdown
        try:
            while True:
                batch.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        if batch:
            self._send(batch)

    def _send(self, batch: list[dict]) -> None:
        if not batch:
            return
        body = json.dumps({"events": batch}, default=str).encode("utf-8")
        req = urllib.request.Request(
            self.dsn.ingest_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"agentminds-python/{__import__('agentminds').__version__}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                if self.debug:
                    log.debug(
                        "agentminds: sent %d events → HTTP %s",
                        len(batch), resp.status,
                    )
        except urllib.error.HTTPError as e:
            # 4xx is configuration error (bad key / disabled site) — drop.
            # 5xx / connection errors: drop too rather than retry forever
            # (background worker already drops oldest under back-pressure).
            if self.debug:
                log.warning("agentminds: HTTP %s — dropped %d events", e.code, len(batch))
        except Exception as e:
            if self.debug:
                log.warning("agentminds: send failed (%s) — dropped %d events", type(e).__name__, len(batch))

    def flush(self, timeout: float | None = 2.0) -> bool:
        """Block until queue drains or timeout. Returns True if drained."""
        deadline = time.monotonic() + (timeout or 2.0)
        while time.monotonic() < deadline:
            if self._queue.empty():
                return True
            time.sleep(0.05)
        return self._queue.empty()

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._worker.join(timeout=SHUTDOWN_TIMEOUT_S)


def client_from_env(**overrides) -> Client | None:
    """Build a Client from AGENTMINDS_* env vars. Returns None if no DSN.

    Env vars:
      AGENTMINDS_DSN       (required if no `dsn` override)
      AGENTMINDS_RELEASE   (optional, falls back to git HEAD if available)
      AGENTMINDS_ENV       (optional, default "production")
      AGENTMINDS_DEBUG     (optional, "1" enables debug log)
    """
    dsn_str = overrides.pop("dsn", None) or os.getenv("AGENTMINDS_DSN", "")
    if not dsn_str:
        return None
    dsn = DSN(dsn_str)
    return Client(
        dsn=dsn,
        release=overrides.pop("release", None) or os.getenv("AGENTMINDS_RELEASE") or _detect_release(),
        environment=overrides.pop("environment", None) or os.getenv("AGENTMINDS_ENV"),
        sample_rate=float(overrides.pop("sample_rate", 1.0)),
        debug=bool(overrides.pop("debug", False) or os.getenv("AGENTMINDS_DEBUG") == "1"),
        send_default_pii=bool(overrides.pop("send_default_pii", False)),
    )


def _detect_release() -> str | None:
    """Auto-detect release from git HEAD if available."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=2,
        )
        return out.decode("ascii").strip() or None
    except Exception:
        return None
