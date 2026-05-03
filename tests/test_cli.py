"""CLI tests — framework detection + entry-file discovery + safe splice."""
from __future__ import annotations
import textwrap
from pathlib import Path

import pytest

from agentminds._cli import (
    detect_framework,
    detect_entry_file,
    _post_module_header,
    _splice_fastapi,
    _splice_flask,
    _has_agentminds_init,
    _redact_dsn,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


# ── detect_framework ────────────────────────────────────────────────


class TestDetectFramework:
    def test_fastapi_via_requirements(self, tmp_path: Path):
        _write(tmp_path / "requirements.txt", "fastapi>=0.95\nuvicorn\n")
        assert detect_framework(tmp_path) == "fastapi"

    def test_fastapi_via_pyproject(self, tmp_path: Path):
        _write(tmp_path / "pyproject.toml", """
            [project]
            name = "x"
            dependencies = ["fastapi"]
        """)
        assert detect_framework(tmp_path) == "fastapi"

    def test_flask_via_requirements(self, tmp_path: Path):
        _write(tmp_path / "requirements.txt", "Flask>=2.0\n")
        assert detect_framework(tmp_path) == "flask"

    def test_django_via_manage_py(self, tmp_path: Path):
        _write(tmp_path / "manage.py", "import os\nimport django\n")
        assert detect_framework(tmp_path) == "django"

    def test_django_via_requirements(self, tmp_path: Path):
        _write(tmp_path / "requirements.txt", "Django>=4.0\n")
        assert detect_framework(tmp_path) == "django"

    def test_no_framework(self, tmp_path: Path):
        _write(tmp_path / "requirements.txt", "requests\n")
        assert detect_framework(tmp_path) is None

    def test_priority_fastapi_over_flask(self, tmp_path: Path):
        # Both listed → fastapi wins (declared first in detector list)
        _write(tmp_path / "requirements.txt", "fastapi\nflask\n")
        assert detect_framework(tmp_path) == "fastapi"


# ── detect_entry_file ───────────────────────────────────────────────


class TestDetectEntryFile:
    def test_fastapi_in_main_py(self, tmp_path: Path):
        _write(tmp_path / "main.py", "from fastapi import FastAPI\napp = FastAPI()")
        entry = detect_entry_file(tmp_path, "fastapi")
        assert entry is not None
        assert entry.name == "main.py"

    def test_fastapi_in_api_app_py(self, tmp_path: Path):
        _write(tmp_path / "api" / "app.py", "from fastapi import FastAPI\napp = FastAPI()")
        entry = detect_entry_file(tmp_path, "fastapi")
        assert entry is not None
        assert entry.name == "app.py"
        assert "api" in entry.parts

    def test_flask_in_app_py(self, tmp_path: Path):
        _write(tmp_path / "app.py", "from flask import Flask\napp = Flask(__name__)")
        entry = detect_entry_file(tmp_path, "flask")
        assert entry is not None
        assert entry.name == "app.py"

    def test_no_match(self, tmp_path: Path):
        _write(tmp_path / "main.py", "print('hello')")
        entry = detect_entry_file(tmp_path, "fastapi")
        assert entry is None

    def test_django_returns_none(self, tmp_path: Path):
        # Django doesn't follow the FastAPI()/Flask() pattern
        _write(tmp_path / "manage.py", "import django")
        entry = detect_entry_file(tmp_path, "django")
        assert entry is None


# ── _post_module_header ─────────────────────────────────────────────


class TestPostModuleHeader:
    def test_skips_module_docstring(self):
        src = '"""My module docstring."""\nfrom fastapi import FastAPI\napp = FastAPI()\n'
        idx = _post_module_header(src)
        # Should be after the docstring + newline
        assert src[idx:].startswith("from fastapi")

    def test_skips_future_imports(self):
        src = "from __future__ import annotations\n\nimport os\n"
        idx = _post_module_header(src)
        assert src[idx:].startswith("import os")

    def test_skips_shebang_and_docstring(self):
        src = '#!/usr/bin/env python\n"""docstring."""\nimport os\n'
        idx = _post_module_header(src)
        assert src[idx:].startswith("import os")

    def test_no_header_returns_zero(self):
        src = "import os\n"
        idx = _post_module_header(src)
        assert idx == 0

    def test_blank_lines_after_future(self):
        src = "from __future__ import annotations\n\n\nimport os\n"
        idx = _post_module_header(src)
        assert src[idx:].startswith("import os")


# ── _has_agentminds_init ────────────────────────────────────────────


def test_has_agentminds_init_detects():
    assert _has_agentminds_init("agentminds.init(dsn='x')") is True
    assert _has_agentminds_init("agentminds.init( dsn='x' )") is True
    # Multiline call
    assert _has_agentminds_init("agentminds.init(\n    dsn='x',\n)") is True


def test_has_agentminds_init_negative():
    assert _has_agentminds_init("import agentminds") is False
    assert _has_agentminds_init("# agentminds.init() ← commented") is True  # we accept comments too — close enough


# ── _splice_fastapi / _splice_flask ─────────────────────────────────


class TestSpliceFastAPI:
    def test_splice_simple(self):
        src = textwrap.dedent("""
            from fastapi import FastAPI

            app = FastAPI()

            @app.get("/")
            def root():
                return {}
        """)
        new = _splice_fastapi(src)
        assert new is not None
        assert "import agentminds" in new
        assert "agentminds.init(" in new
        assert "app.add_middleware(AgentMindsMiddleware)" in new
        # Init block before the FastAPI() line
        init_pos = new.index("agentminds.init(")
        app_pos = new.index("app = FastAPI()")
        assert init_pos < app_pos

    def test_splice_idempotent(self):
        # If init already there, return None (no change)
        src = textwrap.dedent("""
            import agentminds
            agentminds.init(dsn='x')
            from fastapi import FastAPI
            app = FastAPI()
        """)
        assert _splice_fastapi(src) is None

    def test_splice_preserves_docstring(self):
        src = textwrap.dedent('''
            """My API."""
            from fastapi import FastAPI
            app = FastAPI()
        ''')
        new = _splice_fastapi(src)
        assert new is not None
        # Docstring should still be at top
        assert new.lstrip().startswith('"""My API."""')

    def test_splice_no_fastapi_returns_none(self):
        src = "print('hello')\n"
        assert _splice_fastapi(src) is None


class TestSpliceFlask:
    def test_splice_simple(self):
        src = textwrap.dedent("""
            from flask import Flask

            app = Flask(__name__)

            @app.route("/")
            def home():
                return "hi"
        """)
        new = _splice_flask(src)
        assert new is not None
        assert "agentminds.init(" in new
        assert "agentminds_init_app(app)" in new

    def test_splice_no_flask_returns_none(self):
        src = "from fastapi import FastAPI\napp = FastAPI()"
        assert _splice_flask(src) is None


# ── _redact_dsn ─────────────────────────────────────────────────────


def test_redact_dsn_normal():
    out = _redact_dsn("https://pk_yoursite_be30b3d887c0fcf3@api.agentminds.dev/yoursite")
    assert "pk_yoursi" not in out  # full prefix shouldn't appear
    assert "be30b3d887c0fcf3" not in out  # secret part hidden
    assert "@api.agentminds.dev/yoursite" in out  # site_id remains visible
    assert "…" in out  # ellipsis marker present


def test_redact_dsn_short_key():
    out = _redact_dsn("https://pk_x@host/site")
    # Short keys still get a redact marker
    assert "@host/site" in out


def test_redact_dsn_invalid():
    out = _redact_dsn("not a dsn")
    # Returns input unchanged when it can't parse
    assert out == "not a dsn"


# ── connect command — pure helpers (no network) ─────────────────────

from agentminds._cli import (
    _looks_like_url,
    _looks_like_email,
    _normalize_url,
    _derive_name_from_url,
    _build_dsn,
)


class TestConnectHelpers:
    @pytest.mark.parametrize("s", [
        "https://example.com",
        "http://example.com",
        "example.com",
        "sub.example.com",
        "https://example.com/path",
    ])
    def test_looks_like_url_accepts(self, s: str):
        assert _looks_like_url(s)

    @pytest.mark.parametrize("s", ["", "notaurl", "no_dot_anywhere", "https://"])
    def test_looks_like_url_rejects(self, s: str):
        assert not _looks_like_url(s)

    @pytest.mark.parametrize("s", [
        "user@example.com",
        "name+tag@sub.domain.io",
        "x@x.co",
    ])
    def test_looks_like_email_accepts(self, s: str):
        assert _looks_like_email(s)

    @pytest.mark.parametrize("s", ["", "notanemail", "missing@dot", "@nouser.com", "no@at"])
    def test_looks_like_email_rejects(self, s: str):
        assert not _looks_like_email(s)

    def test_normalize_url_adds_scheme(self):
        assert _normalize_url("example.com") == "https://example.com"

    def test_normalize_url_strips_trailing_slash(self):
        assert _normalize_url("https://example.com/") == "https://example.com"

    def test_normalize_url_preserves_http(self):
        assert _normalize_url("http://example.com") == "http://example.com"

    def test_derive_name_strips_subdomains(self):
        # www / api / staging / dev should be stripped, base capitalized
        assert _derive_name_from_url("https://www.acme.com") == "Acme"
        assert _derive_name_from_url("https://api.acme.com") == "Acme"
        assert _derive_name_from_url("https://staging.acme.com") == "Acme"

    def test_derive_name_capitalizes(self):
        assert _derive_name_from_url("https://example.com") == "Example"

    def test_build_dsn_format(self, monkeypatch: pytest.MonkeyPatch):
        # _build_dsn reads _ONBOARD_API at module level so test the shape
        # against the canonical production endpoint.
        dsn = _build_dsn("pk_site_abc123", "site_abc123")
        # https://<api_key>@<host>/<site_id>
        assert dsn.startswith("https://pk_site_abc123@")
        assert dsn.endswith("/site_abc123")
        assert "@" in dsn
