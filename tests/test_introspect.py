"""Code introspection tests — the bit that walks the user's codebase."""
from __future__ import annotations
import ast
import textwrap
from pathlib import Path

import pytest

from agentminds._introspect import (
    extract_code_signature,
    _classify_decorator,
    _decorator_name,
    _extract_imports,
    _stdlib_modules,
)


# ── _stdlib_modules ──────────────────────────────────────────────────


def test_stdlib_modules_includes_core():
    """Core stdlib modules should be detected as stdlib (so they don't
    leak into third_party_deps as false positives)."""
    sl = _stdlib_modules()
    for name in ("os", "sys", "json", "re", "socket", "signal", "struct", "asyncio"):
        assert name in sl, f"{name} missing from stdlib detection"


def test_stdlib_modules_excludes_third_party():
    sl = _stdlib_modules()
    for name in ("fastapi", "flask", "django", "redis", "anthropic"):
        assert name not in sl, f"{name} should not be classified as stdlib"


# ── _decorator_name / _classify_decorator ───────────────────────────


def _parse_first_decorator(src: str) -> ast.AST:
    """Helper: parse `src` and return the first decorator node found."""
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.decorator_list:
                return node.decorator_list[0]
    raise AssertionError("no decorator found")


class TestDecoratorClassification:
    def test_route_with_literal_path(self):
        dec = _parse_first_decorator("""
            @app.get("/users")
            def handler(): pass
        """)
        kind, info = _classify_decorator(dec)
        assert kind == "route"
        assert info == "/users"

    def test_route_router_post(self):
        dec = _parse_first_decorator("""
            @router.post("/api/items")
            def handler(): pass
        """)
        kind, info = _classify_decorator(dec)
        assert kind == "route"
        assert info == "/api/items"

    def test_route_dynamic_path_returns_none(self):
        dec = _parse_first_decorator("""
            @app.get(some_var)
            def handler(): pass
        """)
        kind, info = _classify_decorator(dec)
        assert kind == "route"
        assert info is None

    def test_decorator_non_route(self):
        dec = _parse_first_decorator("""
            @retry
            def handler(): pass
        """)
        kind, info = _classify_decorator(dec)
        assert kind == "decorator"
        assert info == "retry"

    def test_decorator_attribute_chain(self):
        dec = _parse_first_decorator("""
            @app.middleware
            def handler(): pass
        """)
        kind, info = _classify_decorator(dec)
        assert kind == "decorator"
        assert info == "middleware"


class TestDecoratorName:
    def test_simple_name(self):
        dec = _parse_first_decorator("""
            @retry
            def f(): pass
        """)
        assert _decorator_name(dec) == "retry"

    def test_call_form(self):
        dec = _parse_first_decorator("""
            @retry(attempts=3)
            def f(): pass
        """)
        assert _decorator_name(dec) == "retry"

    def test_attribute(self):
        dec = _parse_first_decorator("""
            @app.get("/x")
            def f(): pass
        """)
        assert _decorator_name(dec) == "get"


# ── _extract_imports ─────────────────────────────────────────────────


def test_extract_imports_simple():
    tree = ast.parse(textwrap.dedent("""
        import os
        import sys
        from pathlib import Path
        from agentminds.integrations.fastapi_app import AgentMindsMiddleware
        from .relative import thing
    """))
    pkgs = _extract_imports(tree)
    assert pkgs == {"os", "sys", "pathlib", "agentminds"}
    # Relative imports (module=None or .)don't add a name


def test_extract_imports_aliased():
    tree = ast.parse("import numpy as np")
    pkgs = _extract_imports(tree)
    assert pkgs == {"numpy"}


# ── extract_code_signature — full pipeline ──────────────────────────


def _write_py(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


class TestExtractCodeSignature:
    def test_empty_directory(self, tmp_path: Path):
        sig = extract_code_signature(tmp_path)
        assert sig["language"] == "python"
        assert sig["file_count"] == 0
        assert sig.get("skipped") is True

    def test_invalid_root(self, tmp_path: Path):
        # Pass a path that doesn't exist
        bogus = tmp_path / "nope"
        sig = extract_code_signature(bogus)
        assert "error" in sig

    def test_root_is_a_file_not_dir(self, tmp_path: Path):
        f = tmp_path / "thing.py"
        f.write_text("# nothing")
        sig = extract_code_signature(f)
        assert "error" in sig

    def test_fastapi_detection(self, tmp_path: Path):
        _write_py(tmp_path / "main.py", """
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/users")
            def list_users():
                return []

            @app.post("/users")
            async def create_user():
                return {}
        """)
        sig = extract_code_signature(tmp_path)
        assert sig["language"] == "python"
        assert sig["file_count"] == 1
        assert "fastapi" in sig["frameworks"]
        # Two routes captured
        assert len(sig["routes"]) == 2
        methods = {r["method"] for r in sig["routes"]}
        assert methods == {"GET", "POST"}
        # async_function_count tracks the async route
        assert sig["async_function_count"] == 1
        assert sig["sync_function_count"] == 1

    def test_third_party_excludes_stdlib(self, tmp_path: Path):
        """`socket` and `struct` and similar must not appear in third_party_deps."""
        _write_py(tmp_path / "app.py", """
            import os
            import socket
            import struct
            import requests
            import fastapi
        """)
        sig = extract_code_signature(tmp_path)
        deps = sig["third_party_deps"]
        assert "socket" not in deps
        assert "struct" not in deps
        assert "os" not in deps
        assert "requests" in deps
        assert "fastapi" in deps

    def test_skip_dirs_respected(self, tmp_path: Path):
        # Code in skipped dirs shouldn't be parsed
        _write_py(tmp_path / "real.py", "import fastapi")
        _write_py(tmp_path / "node_modules" / "junk.py", "import django")
        _write_py(tmp_path / ".venv" / "site_packages.py", "import flask")
        sig = extract_code_signature(tmp_path)
        assert sig["file_count"] == 1
        # Frameworks include fastapi (real), exclude django/flask (skipped)
        assert "fastapi" in sig["frameworks"]
        assert "django" not in sig["frameworks"]
        assert "flask" not in sig["frameworks"]

    def test_signature_hash_is_stable(self, tmp_path: Path):
        _write_py(tmp_path / "x.py", "import fastapi")
        sig1 = extract_code_signature(tmp_path)
        sig2 = extract_code_signature(tmp_path)
        assert sig1["signature_hash"] == sig2["signature_hash"]

    def test_signature_hash_changes_with_deps(self, tmp_path: Path):
        _write_py(tmp_path / "x.py", "import fastapi")
        sig1 = extract_code_signature(tmp_path)
        _write_py(tmp_path / "x.py", "import fastapi\nimport redis")
        sig2 = extract_code_signature(tmp_path)
        assert sig1["signature_hash"] != sig2["signature_hash"]

    def test_function_count_is_int(self, tmp_path: Path):
        # Regression: function_count was once a list len; must be int now
        _write_py(tmp_path / "x.py", "def a(): pass\ndef b(): pass\nasync def c(): pass")
        sig = extract_code_signature(tmp_path)
        assert isinstance(sig["function_count"], int)
        assert sig["function_count"] == 3
        assert sig["async_function_count"] == 1
        assert sig["sync_function_count"] == 2

    def test_parse_errors_dont_crash(self, tmp_path: Path):
        # Broken syntax in one file shouldn't kill the whole pass
        _write_py(tmp_path / "broken.py", "def )))(((")
        _write_py(tmp_path / "ok.py", "import fastapi")
        sig = extract_code_signature(tmp_path)
        assert sig["parse_errors"] == 1
        assert "fastapi" in sig["frameworks"]
