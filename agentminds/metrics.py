"""Canonical metric emitters for AgentMinds reports.

Mirror of the server-side registry at `master-agent-system/sync/
metric_registry.py`. Sites pushing reports through the Python SDK
should use these helpers instead of writing free-form metric dicts —
the canonical names go through to the cross-site benchmark surface
automatically, and your push will get
`_meta.metric_registry.status: "all_canonical"` in the response.

Usage
-----

    from agentminds import metrics

    # Build canonical seo metrics
    seo_data = metrics.seo(
        landing_status_code=200,
        sitemap_url_count=42,
        meta_description_length=158,
        h1_count=1,
        json_ld_blocks_count=2,
        robots_txt_present=1,
        core_web_vitals_pass=1,
    )

    # Push as part of a report
    requests.post(
        "https://api.agentminds.dev/api/v1/sync/report",
        headers={"X-AgentMinds-Key": YOUR_KEY},
        json={
            "site_id": "your_site",
            "agent": "seo",
            "report": {
                "severity": "info",
                "summary": "Daily SEO check",
                "metrics": seo_data,
                ...
            },
            ...
        },
    )

Naming convention
-----------------

  - lowercase ASCII, snake_case
  - one unit suffix per metric (`_ms`, `_pct`, `_count`, `_bytes`,
    `_per_second`, `_ratio`)
  - boolean signals as `<base>_present` with 0/1 numeric value

Strict signature
----------------

Each emitter takes ONLY the canonical fields as keyword arguments — pass
an unknown field and you get TypeError at the call site. This is
intentional: catch typos at import / first-use rather than at the
server-side soft-warn (which only fires on push).

To propose new canonical metrics, open a PR against
`master-agent-system/sync/metric_registry.py` and `metrics.py` here.
"""
from __future__ import annotations

from typing import Any


def _drop_none(d: dict[str, Any]) -> dict[str, float]:
    """Drop None-valued kwargs so callers can pass only what they have."""
    return {k: v for k, v in d.items() if v is not None}


# ─── Web hygiene / public-surface agents ─────────────────────────────


def seo(
    *,
    landing_status_code: int | None = None,
    sitemap_url_count: int | None = None,
    robots_txt_present: int | None = None,
    meta_description_length: int | None = None,
    core_web_vitals_pass: int | None = None,
    h1_count: int | None = None,
    json_ld_blocks_count: int | None = None,
) -> dict[str, float]:
    """Canonical metrics for the seo agent. Pass only what you measure."""
    return _drop_none({
        "landing_status_code": landing_status_code,
        "sitemap_url_count": sitemap_url_count,
        "robots_txt_present": robots_txt_present,
        "meta_description_length": meta_description_length,
        "core_web_vitals_pass": core_web_vitals_pass,
        "h1_count": h1_count,
        "json_ld_blocks_count": json_ld_blocks_count,
    })


def live_seo(
    *,
    landing_status_code: int | None = None,
    sitemap_url_count: int | None = None,
    robots_txt_present: int | None = None,
    meta_description_length: int | None = None,
) -> dict[str, float]:
    """Canonical metrics for live_seo (real-time SEO scan)."""
    return _drop_none({
        "landing_status_code": landing_status_code,
        "sitemap_url_count": sitemap_url_count,
        "robots_txt_present": robots_txt_present,
        "meta_description_length": meta_description_length,
    })


def security(
    *,
    hsts_present: int | None = None,
    csp_present: int | None = None,
    x_frame_options_present: int | None = None,
    x_content_type_options_present: int | None = None,
    referrer_policy_present: int | None = None,
    permissions_policy_present: int | None = None,
    ssl_days_remaining: int | None = None,
    mixed_content_count: int | None = None,
    cors_origins_count: int | None = None,
) -> dict[str, float]:
    """Canonical metrics for the security agent."""
    return _drop_none({
        "hsts_present": hsts_present,
        "csp_present": csp_present,
        "x_frame_options_present": x_frame_options_present,
        "x_content_type_options_present": x_content_type_options_present,
        "referrer_policy_present": referrer_policy_present,
        "permissions_policy_present": permissions_policy_present,
        "ssl_days_remaining": ssl_days_remaining,
        "mixed_content_count": mixed_content_count,
        "cors_origins_count": cors_origins_count,
    })


def live_security(
    *,
    hsts_present: int | None = None,
    csp_present: int | None = None,
    x_frame_options_present: int | None = None,
) -> dict[str, float]:
    """Canonical metrics for live_security (real-time header scan)."""
    return _drop_none({
        "hsts_present": hsts_present,
        "csp_present": csp_present,
        "x_frame_options_present": x_frame_options_present,
    })


# ─── Runtime / health agents ─────────────────────────────────────────


def performance(
    *,
    response_time_ms_p50: float | None = None,
    response_time_ms_p95: float | None = None,
    response_time_ms_p99: float | None = None,
    throughput_rps: float | None = None,
    error_rate_pct: float | None = None,
    memory_usage_mb: float | None = None,
    cpu_usage_pct: float | None = None,
) -> dict[str, float]:
    """Canonical metrics for the performance agent."""
    return _drop_none({
        "response_time_ms_p50": response_time_ms_p50,
        "response_time_ms_p95": response_time_ms_p95,
        "response_time_ms_p99": response_time_ms_p99,
        "throughput_rps": throughput_rps,
        "error_rate_pct": error_rate_pct,
        "memory_usage_mb": memory_usage_mb,
        "cpu_usage_pct": cpu_usage_pct,
    })


def health(
    *,
    uptime_pct: float | None = None,
    last_pipeline_status: str | None = None,
    open_circuits_count: int | None = None,
    alerts_1h_count: int | None = None,
) -> dict[str, Any]:
    """Canonical metrics for the health agent. last_pipeline_status is a
    string enum (ok/error/unknown) — kept here despite the convention's
    numeric preference because operational signals often carry status
    text. Server-side tolerates string values."""
    return _drop_none({
        "uptime_pct": uptime_pct,
        "last_pipeline_status": last_pipeline_status,
        "open_circuits_count": open_circuits_count,
        "alerts_1h_count": alerts_1h_count,
    })


def uptime(
    *,
    web_response_time_ms: float | None = None,
    api_response_time_ms: float | None = None,
    ssl_days_remaining: int | None = None,
) -> dict[str, float]:
    """Canonical metrics for the uptime agent."""
    return _drop_none({
        "web_response_time_ms": web_response_time_ms,
        "api_response_time_ms": api_response_time_ms,
        "ssl_days_remaining": ssl_days_remaining,
    })


def error(
    *,
    errors_1h_count: int | None = None,
    errors_24h_count: int | None = None,
    deploy_failures_recent_count: int | None = None,
) -> dict[str, int]:
    """Canonical metrics for the error agent."""
    return _drop_none({
        "errors_1h_count": errors_1h_count,
        "errors_24h_count": errors_24h_count,
        "deploy_failures_recent_count": deploy_failures_recent_count,
    })


# ─── DB / infra agents ───────────────────────────────────────────────


def database(
    *,
    connection_pool_utilization_pct: float | None = None,
    query_time_ms_p95: float | None = None,
    slow_query_count: int | None = None,
    replication_lag_seconds: float | None = None,
) -> dict[str, float]:
    """Canonical metrics for the database agent."""
    return _drop_none({
        "connection_pool_utilization_pct": connection_pool_utilization_pct,
        "query_time_ms_p95": query_time_ms_p95,
        "slow_query_count": slow_query_count,
        "replication_lag_seconds": replication_lag_seconds,
    })


def infra(
    *,
    deploy_count_24h: int | None = None,
    deploy_duration_seconds: float | None = None,
    container_restarts_24h: int | None = None,
) -> dict[str, float]:
    """Canonical metrics for the infra agent."""
    return _drop_none({
        "deploy_count_24h": deploy_count_24h,
        "deploy_duration_seconds": deploy_duration_seconds,
        "container_restarts_24h": container_restarts_24h,
    })


# ─── Content / SEO+ agents ───────────────────────────────────────────


def content(
    *,
    blog_post_count: int | None = None,
    newest_post_age_days: int | None = None,
    stale_posts_90d_count: int | None = None,
) -> dict[str, int]:
    """Canonical metrics for the content agent."""
    return _drop_none({
        "blog_post_count": blog_post_count,
        "newest_post_age_days": newest_post_age_days,
        "stale_posts_90d_count": stale_posts_90d_count,
    })


# ─── Behavioral / business agents ────────────────────────────────────


def user_behavior(
    *,
    user_count_total: int | None = None,
    user_count_active: int | None = None,
    dau_mau_ratio_pct: float | None = None,
    churn_rate_pct: float | None = None,
) -> dict[str, float]:
    """Canonical metrics for the user_behavior agent."""
    return _drop_none({
        "user_count_total": user_count_total,
        "user_count_active": user_count_active,
        "dau_mau_ratio_pct": dau_mau_ratio_pct,
        "churn_rate_pct": churn_rate_pct,
    })


def feedback(
    *,
    feedback_count_total: int | None = None,
    irrelevant_tip_count: int | None = None,
    site_type_corrections_count: int | None = None,
) -> dict[str, int]:
    """Canonical metrics for the feedback agent."""
    return _drop_none({
        "feedback_count_total": feedback_count_total,
        "irrelevant_tip_count": irrelevant_tip_count,
        "site_type_corrections_count": site_type_corrections_count,
    })


def growth(
    *,
    registered_sites_count: int | None = None,
    active_sites_count: int | None = None,
    patterns_observed_count: int | None = None,
    actionable_patterns_count: int | None = None,
) -> dict[str, int]:
    """Canonical metrics for the growth agent."""
    return _drop_none({
        "registered_sites_count": registered_sites_count,
        "active_sites_count": active_sites_count,
        "patterns_observed_count": patterns_observed_count,
        "actionable_patterns_count": actionable_patterns_count,
    })


# ─── Pipeline / orchestration ────────────────────────────────────────


def pipeline(
    *,
    last_run_status: str | None = None,
    last_run_duration_seconds: float | None = None,
    last_run_age_hours: float | None = None,
    alerts_count: int | None = None,
) -> dict[str, Any]:
    """Canonical metrics for the pipeline agent. last_run_status is a
    string enum (ok/error/unknown)."""
    return _drop_none({
        "last_run_status": last_run_status,
        "last_run_duration_seconds": last_run_duration_seconds,
        "last_run_age_hours": last_run_age_hours,
        "alerts_count": alerts_count,
    })


def freshness(
    *,
    pool_age_hours: float | None = None,
    stale_agents_count: int | None = None,
    stale_sites_count: int | None = None,
) -> dict[str, float]:
    """Canonical metrics for the freshness agent."""
    return _drop_none({
        "pool_age_hours": pool_age_hours,
        "stale_agents_count": stale_agents_count,
        "stale_sites_count": stale_sites_count,
    })


# ─── Discovery helpers ───────────────────────────────────────────────


def supported_agents() -> list[str]:
    """Return a sorted list of agent types this module has emitters for.
    Mirrors the server-side `GET /api/v1/sync/metric-registry` index."""
    return sorted([
        "seo", "live_seo", "security", "live_security",
        "performance", "health", "uptime", "error",
        "database", "infra",
        "content",
        "user_behavior", "feedback", "growth",
        "pipeline", "freshness",
    ])


__all__ = supported_agents() + ["supported_agents"]
