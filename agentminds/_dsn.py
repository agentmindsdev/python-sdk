"""DSN parser — Sentry-style URL → site_id + public_key + api_base.

Format: https://pk_yoursite_xxx@api.agentminds.dev/yoursite

Components:
  - scheme://     -- https or http
  - public_key@   -- pk_<slug>_<random>, browser-safe write-only key
  - host          -- api.agentminds.dev (or custom)
  - /site_id      -- the site identifier
"""
from __future__ import annotations
from urllib.parse import urlparse


class InvalidDSN(ValueError):
    pass


class DSN:
    __slots__ = ("public_key", "host", "scheme", "site_id", "api_base", "ingest_url")

    def __init__(self, dsn: str):
        if not dsn or "@" not in dsn or "://" not in dsn:
            raise InvalidDSN(
                f"DSN must look like 'https://pk_xxx@api.agentminds.dev/site_id', got: {dsn!r}"
            )
        parsed = urlparse(dsn)
        if not parsed.username:
            raise InvalidDSN("DSN missing public key — username portion before @")
        if not parsed.hostname:
            raise InvalidDSN("DSN missing host")
        site_id = parsed.path.lstrip("/").rstrip("/")
        if not site_id:
            raise InvalidDSN("DSN missing site_id — path component after host")
        if "/" in site_id:
            raise InvalidDSN(f"DSN site_id must be a single segment, got: {site_id!r}")

        self.public_key = parsed.username
        self.host = parsed.hostname
        self.scheme = parsed.scheme or "https"
        port = f":{parsed.port}" if parsed.port else ""
        self.site_id = site_id
        self.api_base = f"{self.scheme}://{self.host}{port}"
        self.ingest_url = (
            f"{self.api_base}/api/v1/sync/ingest/{self.site_id}/events"
            f"?key={self.public_key}"
        )

    def __repr__(self) -> str:
        return (
            f"DSN(site_id={self.site_id!r}, host={self.host!r}, "
            f"public_key={self.public_key[:8]}…)"
        )
