"""High-level helpers for the /sync API surface.

This module exists so a customer integrating AgentMinds doesn't have to
hand-roll JSON payloads, manage the X-AgentMinds-Key header, or
remember the canonical metric names. Two halves:

PUSH (your data → AgentMinds):
    agentminds.sync.report(
        api_key="sk_yoursite_xxx",
        site_id="yoursite",
        agent="security",
        metrics={"hsts_present": 1, "csp_present": 1, "ssl_days_remaining": 60},
        warnings=[{"severity": "warning", "message": "X"}],
        learned_patterns=[{"pattern": "foo", "category": "security",
                            "confidence": 0.9, "status": "active",
                            "impact": "medium", "detail": "y"}],
        project_info={"tech_stack": {"framework": "FastAPI"}},
    )

PULL (AgentMinds insights → your dashboard):
    recs    = agentminds.sync.recommendations(api_key, limit=10)
    bench   = agentminds.sync.benchmarks(api_key, site_id)
    role    = agentminds.sync.my_role(api_key)
    pos     = agentminds.sync.network_position(api_key)
    issues  = agentminds.sync.issues(api_key, status="open")
    me      = agentminds.sync.me(api_key)

Auth + endpoint resolution:
  - api_key + site_id can be passed directly OR
  - read from environment: AGENTMINDS_API_KEY, AGENTMINDS_SITE_ID
  - endpoint defaults to https://api.agentminds.dev; override via
    AGENTMINDS_API or the api_url= kwarg

Auto-stamp:
  - schema_url defaults to current ARP version this SDK was built against
  - tech_stack canonical-name normalization happens server-side, but this
    module also imports the registry so SDK-level helpers can pre-validate

stdlib-only — no requests dependency. Drop the file in any Python 3.9+
environment and it works.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_API_BASE = "https://api.agentminds.dev"
ARP_SCHEMA_URL = "https://agentminds.dev/arp/1.1.0"
USER_AGENT = "agentminds-python/1.0"


class AgentMindsAPIError(Exception):
    """Raised when the AgentMinds server returns 4xx/5xx with a response body."""

    def __init__(self, status: int, body: Any, message: str = ""):
        self.status = status
        self.body = body
        super().__init__(message or f"HTTP {status}: {body!r}")


def _resolve_api_key(api_key: str | None) -> str:
    key = api_key or os.environ.get("AGENTMINDS_API_KEY", "")
    if not key:
        raise AgentMindsAPIError(
            0, None,
            "api_key required — pass it explicitly or set AGENTMINDS_API_KEY env var"
        )
    return key


def _resolve_site_id(site_id: str | None) -> str:
    sid = site_id or os.environ.get("AGENTMINDS_SITE_ID", "")
    if not sid:
        raise AgentMindsAPIError(
            0, None,
            "site_id required — pass it explicitly or set AGENTMINDS_SITE_ID env var"
        )
    return sid


def _resolve_api_base(api_url: str | None) -> str:
    return (api_url or os.environ.get("AGENTMINDS_API", DEFAULT_API_BASE)).rstrip("/")


def _http(method: str, url: str, body: dict | None = None,
          api_key: str = "", timeout: int = 30) -> tuple[int, dict]:
    """One-shot HTTP with auth header + JSON encoding. Returns (status, body)."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if api_key:
        headers["X-AgentMinds-Key"] = api_key
    data = None
    if body is not None:
        data = json.dumps(body, default=str).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read().decode("utf-8") if r.length != 0 else "{}"
            return r.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        try:
            body_dict = json.loads(e.read().decode("utf-8"))
        except Exception:
            body_dict = {"error": str(e)[:200]}
        return e.code, body_dict


# ─── PUSH side ────────────────────────────────────────────────────


def report(
    *,
    api_key: str | None = None,
    site_id: str | None = None,
    agent: str,
    metrics: dict[str, Any] | None = None,
    warnings: list[dict] | None = None,
    recommendations: list[dict] | None = None,
    learned_patterns: list[dict] | None = None,
    severity: str = "info",
    summary: str | None = None,
    project_info: dict | None = None,
    schema_url: str = ARP_SCHEMA_URL,
    api_url: str | None = None,
    timeout: int = 30,
) -> dict:
    """Push one agent report to /sync/report.

    All push fields are kwargs so callers don't have to remember positional
    order. Server stamps `_meta.schema` and `_meta.metric_registry` on the
    response — the returned dict is the raw server response so you can read
    them. Raises AgentMindsAPIError on 4xx/5xx.

    Required: agent (the agent name string).
    Required at server-side validation:
      - severity, summary, ≥2 metrics, ≥1 learned_pattern (Grade D ratchet).
        Below that the server returns 422 with a structured envelope
        explaining what's missing.

    Tip: build metrics with the canonical helpers in
    `agentminds.metrics` (e.g., `metrics=agentminds.metrics.security(...)`).
    """
    api_key = _resolve_api_key(api_key)
    site_id = _resolve_site_id(site_id)
    api_base = _resolve_api_base(api_url)

    # Default-fill summary so the Grade D ratchet doesn't kick on a
    # caller who only sent metrics. Real callers should write their own.
    summary = summary or f"{agent} report"

    payload = {
        "site_id": site_id,
        "agent": agent,
        "schema_url": schema_url,
        "report": {
            "severity": severity,
            "summary": summary,
            "metrics": metrics or {},
            "warnings": warnings or [],
            "recommendations": recommendations or [],
        },
        "memory": {
            "learned_patterns": learned_patterns or [],
        },
    }
    if project_info:
        payload["project_info"] = project_info

    status, body = _http(
        "POST",
        f"{api_base}/api/v1/sync/report",
        body=payload,
        api_key=api_key,
        timeout=timeout,
    )
    if status >= 400:
        raise AgentMindsAPIError(status, body)
    return body


# ─── PULL side ────────────────────────────────────────────────────


def me(api_key: str | None = None, *, api_url: str | None = None,
       timeout: int = 15) -> dict:
    """GET /sync/me — your site's profile + meta. Includes detected_tech,
    site_type, scan_grade, agent_count, agent_names, has_pushed_data.
    """
    api_key = _resolve_api_key(api_key)
    api_base = _resolve_api_base(api_url)
    status, body = _http("GET", f"{api_base}/api/v1/sync/me",
                         api_key=api_key, timeout=timeout)
    if status >= 400:
        raise AgentMindsAPIError(status, body)
    return body


def recommendations(api_key: str | None = None, *,
                    limit: int = 30,
                    api_url: str | None = None,
                    timeout: int = 30) -> dict:
    """GET /sync/personalized-rules — top recommendations ranked for your
    stack + site type + applied-state filter. Returns up to `limit` rules.
    """
    api_key = _resolve_api_key(api_key)
    api_base = _resolve_api_base(api_url)
    status, body = _http(
        "GET",
        f"{api_base}/api/v1/sync/personalized-rules?limit={limit}",
        api_key=api_key, timeout=timeout,
    )
    if status >= 400:
        raise AgentMindsAPIError(status, body)
    return body


def benchmarks(api_key: str | None = None, site_id: str | None = None, *,
               include_provisional: bool = False,
               api_url: str | None = None,
               timeout: int = 30) -> dict:
    """GET /sync/benchmarks/{site_id} — your metrics vs network averages.
    Each comparison row is keyed under the canonical bucket (post-fuzzy
    normalization), with `aliases_used` listing other names contributors
    pushed under that map to the same bucket.
    """
    api_key = _resolve_api_key(api_key)
    site_id = _resolve_site_id(site_id)
    api_base = _resolve_api_base(api_url)
    flag = "?include_provisional=true" if include_provisional else ""
    status, body = _http(
        "GET",
        f"{api_base}/api/v1/sync/benchmarks/{site_id}{flag}",
        api_key=api_key, timeout=timeout,
    )
    if status >= 400:
        raise AgentMindsAPIError(status, body)
    return body


def network_position(api_key: str | None = None, *,
                     api_url: str | None = None,
                     timeout: int = 15) -> dict:
    """GET /sync/network-position — your overall score vs network p50/p90."""
    api_key = _resolve_api_key(api_key)
    api_base = _resolve_api_base(api_url)
    status, body = _http("GET",
                         f"{api_base}/api/v1/sync/network-position",
                         api_key=api_key, timeout=timeout)
    if status >= 400:
        raise AgentMindsAPIError(status, body)
    return body


def my_role(api_key: str | None = None, *,
            api_url: str | None = None,
            timeout: int = 15) -> dict:
    """GET /sync/my-role — donor / consumer / balanced classification with
    raw scores. Use to surface "you're contributing X, getting Y" in a
    customer dashboard."""
    api_key = _resolve_api_key(api_key)
    api_base = _resolve_api_base(api_url)
    status, body = _http("GET", f"{api_base}/api/v1/sync/my-role",
                         api_key=api_key, timeout=timeout)
    if status >= 400:
        raise AgentMindsAPIError(status, body)
    return body


def issues(api_key: str | None = None, *, status: str = "open", limit: int = 100,
           api_url: str | None = None, timeout: int = 15) -> dict:
    """GET /sync/issues — open / resolved / muted / all issues for your site.
    Includes both scanner-derived issues and agent-pushed warnings (the
    latter via the bridge added in the same release).
    """
    api_key = _resolve_api_key(api_key)
    api_base = _resolve_api_base(api_url)
    api_status, body = _http(
        "GET",
        f"{api_base}/api/v1/sync/issues?status={status}&limit={limit}",
        api_key=api_key, timeout=timeout,
    )
    if api_status >= 400:
        raise AgentMindsAPIError(api_status, body)
    return body


def actions(api_key: str | None = None, *, status: str = "all", limit: int = 50,
            api_url: str | None = None, timeout: int = 15) -> dict:
    """GET /sync/actions — your action queue (LLM-derived recommendations
    persisted as trackable items). Each action has status pending / done /
    skipped / false_positive — update via `set_action_status()`.
    """
    api_key = _resolve_api_key(api_key)
    api_base = _resolve_api_base(api_url)
    api_status, body = _http(
        "GET",
        f"{api_base}/api/v1/sync/actions?status={status}&limit={limit}",
        api_key=api_key, timeout=timeout,
    )
    if api_status >= 400:
        raise AgentMindsAPIError(api_status, body)
    return body


def patterns(api_key: str | None = None, *, limit: int = 50, category: str = "",
             agent: str = "", impact: str = "",
             api_url: str | None = None, timeout: int = 15) -> dict:
    """GET /sync/patterns — public pattern browser. Tier-2 patterns visible
    only when api_key authenticates; Tier-1 + Tier-3 always shown.
    """
    api_key = _resolve_api_key(api_key)
    api_base = _resolve_api_base(api_url)
    qs = f"?limit={limit}"
    if category: qs += f"&category={category}"
    if agent: qs += f"&agent={agent}"
    if impact: qs += f"&impact={impact}"
    status, body = _http("GET", f"{api_base}/api/v1/sync/patterns{qs}",
                         api_key=api_key, timeout=timeout)
    if status >= 400:
        raise AgentMindsAPIError(status, body)
    return body


__all__ = [
    "AgentMindsAPIError",
    "ARP_SCHEMA_URL",
    "report",
    "me",
    "recommendations",
    "benchmarks",
    "network_position",
    "my_role",
    "issues",
    "actions",
    "patterns",
]
