"""DSN parser tests — the surface every consumer hits first."""
from __future__ import annotations
import pytest

from agentminds._dsn import DSN, InvalidDSN


class TestDSNParsing:
    def test_minimal_valid(self):
        d = DSN("https://pk_test_abc@api.agentminds.dev/yoursite")
        assert d.public_key == "pk_test_abc"
        assert d.host == "api.agentminds.dev"
        assert d.scheme == "https"
        assert d.site_id == "yoursite"
        assert d.api_base == "https://api.agentminds.dev"
        assert d.ingest_url == "https://api.agentminds.dev/api/v1/sync/ingest/yoursite/events?key=pk_test_abc"

    def test_with_port(self):
        d = DSN("http://pk_test@localhost:8000/site")
        assert d.host == "localhost"
        assert d.api_base == "http://localhost:8000"
        assert d.ingest_url.startswith("http://localhost:8000/")

    def test_site_id_url_encoded(self):
        # site_ids with special chars get URL-encoded in the path component
        d = DSN("https://pk_x@host/my-site_42")
        assert d.site_id == "my-site_42"
        # encodeURIComponent keeps these chars unchanged
        assert "/my-site_42/events" in d.ingest_url

    def test_strips_trailing_slash(self):
        d = DSN("https://pk_x@host/site/")
        assert d.site_id == "site"


class TestDSNValidation:
    def test_empty_string(self):
        with pytest.raises(InvalidDSN):
            DSN("")

    def test_not_a_url(self):
        with pytest.raises(InvalidDSN):
            DSN("definitely not a url")

    def test_missing_username(self):
        with pytest.raises(InvalidDSN):
            DSN("https://api.agentminds.dev/site")

    def test_missing_path(self):
        with pytest.raises(InvalidDSN):
            DSN("https://pk_test@api.agentminds.dev/")

    def test_missing_at_separator(self):
        # Should detect the malformed shape via the early "@" check
        with pytest.raises(InvalidDSN):
            DSN("https://api.agentminds.dev/site")

    def test_multi_segment_path_rejected(self):
        with pytest.raises(InvalidDSN):
            DSN("https://pk_test@host/my/nested/path")
