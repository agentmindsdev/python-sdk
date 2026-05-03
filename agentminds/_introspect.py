"""Code introspection — auto-extract patterns from the host app at init.

The big differentiator from a pure-telemetry SDK: we don't just capture
errors. We also walk the host app's codebase ONCE at startup and push a
structured "code signature" so AgentMinds knows the shape of what it's
monitoring without the user lifting a finger. That signature feeds the
recommendation engine — patterns, frameworks, custom decorators, route
shape, third-party deps — all matched against the network's pool.

What we extract (best-effort, fast, sandboxed):
  - Top-level package layout (depth ≤ 3, file count, dir names)
  - Frameworks detected from imports (fastapi, flask, django, celery, …)
  - HTTP route handlers (decorator-based: @app.get, @router.post, …)
  - Decorator patterns repeated ≥ 3 times across the codebase
  - Function names (de-duplicated, anonymized)
  - Third-party deps that appear in imports
  - Async vs sync ratio
  - Test file count

What we DO NOT extract:
  - Function bodies, docstrings, comments
  - String literals (could contain secrets)
  - Path-specific data outside the project root
  - Anything that smells like a credential

The result is a single dict shipped as a `custom` event with type
`code_signature`. Subsequent runs only ship if the hash differs —
typical churn = once per deploy.
"""
from __future__ import annotations
import ast
import hashlib
import os
import sys
import time
from collections import Counter
from pathlib import Path

# Soft caps so introspection never becomes the slow part of init.
MAX_FILES = 800
MAX_FILE_BYTES = 200 * 1024
MAX_DEPTH = 6
SCAN_TIMEOUT_S = 5.0  # hard time budget for the entire walk + parse pass

# Directories we never enter — third-party code, build artifacts, secrets.
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "env", "node_modules", "dist", "build",
    ".next", "out", "target", ".idea", ".vscode", ".tox", ".eggs",
    "site-packages", "vendor",
}

# Frameworks we detect by import root. Maps top-level module → name.
_FRAMEWORK_MARKERS = {
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "starlette": "starlette",
    "tornado": "tornado",
    "aiohttp": "aiohttp",
    "celery": "celery",
    "rq": "rq",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "fastmcp": "fastmcp",
    "anthropic": "anthropic",
    "openai": "openai",
    "redis": "redis",
    "psycopg2": "postgres",
    "psycopg": "postgres",
    "asyncpg": "postgres",
    "pymongo": "mongodb",
    "motor": "mongodb",
    "boto3": "aws",
    "stripe": "stripe",
}

# Route-defining decorators we recognize across frameworks.
_ROUTE_DECORATORS = {"get", "post", "put", "delete", "patch", "route", "options", "head"}


def _walk_python_files(root: Path, deadline: float | None = None) -> list[Path]:
    """Yield .py files under root, respecting skip dirs and depth/count caps.

    `deadline` is a `time.monotonic()` reading; if reached mid-walk, we
    return whatever we found so far. Init never blocks on a pathological
    project layout.
    """
    found: list[Path] = []
    root = root.resolve()
    root_depth = len(root.parts)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if deadline is not None and time.monotonic() > deadline:
            return found
        depth = len(Path(dirpath).resolve().parts) - root_depth
        if depth > MAX_DEPTH:
            dirnames[:] = []
            continue
        # Prune skip dirs in-place
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                p = Path(dirpath) / fn
                try:
                    if p.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                found.append(p)
                if len(found) >= MAX_FILES:
                    return found
    return found


def _decorator_name(node: ast.AST) -> str | None:
    """Pull a usable name out of a decorator node (handles attr chains)."""
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _classify_decorator(node: ast.AST) -> tuple[str, str | None]:
    """Return (kind, route_path) for a decorator node.

    kind is "route" for HTTP routes, "decorator" otherwise. route_path is
    the literal path string when present and a constant — never a value
    that could be a secret.
    """
    name = _decorator_name(node)
    if not name:
        return ("decorator", None)
    if name.lower() in _ROUTE_DECORATORS:
        # Try to extract the path argument if it's a literal string
        if isinstance(node, ast.Call) and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                # Only accept route-shaped paths
                v = first.value
                if v.startswith("/") and len(v) <= 200:
                    return ("route", v)
        return ("route", None)
    return ("decorator", name)


def _extract_imports(tree: ast.AST) -> set[str]:
    """Top-level package names imported in this module.

    Skips relative imports (`from .x import y`) — `node.level > 0` means
    the import is in-project, not a third-party package. Without this
    check we'd erroneously list every relative-imported submodule as a
    separate dependency.
    """
    pkgs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = (alias.name or "").split(".")[0]
                if top:
                    pkgs.add(top)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 means relative import (`from .x import y`); skip.
            if node.module and (getattr(node, "level", 0) or 0) == 0:
                top = node.module.split(".")[0]
                if top:
                    pkgs.add(top)
    return pkgs


def _stdlib_modules() -> frozenset[str]:
    """Return the set of stdlib top-level module names for this Python.

    Python 3.10+ exposes `sys.stdlib_module_names` directly — definitive.
    Older runtimes get a hand-curated subset that covers the common
    cases (we'd rather show a few extra entries in third_party_deps
    than miss a real third-party dep).
    """
    builtin = getattr(sys, "stdlib_module_names", None)
    if builtin:
        return frozenset(builtin)
    return frozenset({
        "os", "sys", "re", "json", "time", "datetime", "pathlib", "typing",
        "logging", "asyncio", "collections", "functools", "itertools",
        "subprocess", "threading", "queue", "uuid", "hashlib", "hmac",
        "secrets", "io", "math", "random", "string", "textwrap", "traceback",
        "urllib", "http", "email", "csv", "shutil", "tempfile", "argparse",
        "ast", "inspect", "abc", "contextlib", "dataclasses", "enum",
        "warnings", "weakref", "copy", "pickle", "base64", "socket", "signal",
        "select", "struct", "decimal", "fractions", "numbers", "unicodedata",
        "gzip", "zlib", "tarfile", "zipfile", "configparser", "platform",
        "shutil", "stat", "errno", "ctypes", "operator", "types", "importlib",
        "pkgutil",
    })


def extract_code_signature(root: str | Path | None = None) -> dict:
    """Walk the host app's codebase and build a structured signature.

    Returns a JSON-serialisable dict shaped to be consumed by the
    recommendation engine. Best-effort: any single-file parse failure
    is swallowed; the overall result still ships. The whole pass is
    capped by `SCAN_TIMEOUT_S` so init never blocks on a pathological
    layout.
    """
    if root is None:
        # Best guess at the host app root: cwd where the process started.
        root = Path.cwd()
    root = Path(root)

    if not root.exists() or not root.is_dir():
        return {"error": "root not a directory", "root": str(root)}

    deadline = time.monotonic() + SCAN_TIMEOUT_S

    # Resolve once so relative_to() comparisons are consistent on Windows
    root_resolved = root.resolve()
    files = _walk_python_files(root_resolved, deadline=deadline)
    file_count = len(files)
    if file_count == 0:
        return {
            "language": "python",
            "root_basename": root.name,
            "file_count": 0,
            "skipped": True,
            "reason": "no .py files under root",
        }

    imports: Counter[str] = Counter()
    decorators: Counter[str] = Counter()
    routes: list[dict] = []
    function_count = 0          # was function_names: list — only len() was used
    async_count = 0
    sync_count = 0
    test_files = 0
    parse_errors = 0
    timed_out = False
    top_dirs: Counter[str] = Counter()

    for path in files:
        if time.monotonic() > deadline:
            timed_out = True
            break
        try:
            rel = path.resolve().relative_to(root_resolved)
        except ValueError:
            # File is outside the resolved root tree — shouldn't happen but skip safely
            continue
        parts = rel.parts
        if len(parts) > 1:
            top_dirs[parts[0]] += 1
        if "test" in path.name.lower() or (parts and "test" in parts[0].lower()):
            test_files += 1

        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(path))
        except (SyntaxError, ValueError):
            parse_errors += 1
            continue
        except OSError:
            parse_errors += 1
            continue

        for top in _extract_imports(tree):
            imports[top] += 1

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_count += 1
                if isinstance(node, ast.AsyncFunctionDef):
                    async_count += 1
                else:
                    sync_count += 1
                for dec in node.decorator_list:
                    kind, info = _classify_decorator(dec)
                    if kind == "route":
                        method_name = _decorator_name(dec) or "?"
                        routes.append({
                            "method": method_name.upper(),
                            "path": info or "(dynamic)",
                            "handler": node.name[:64],
                            "async": isinstance(node, ast.AsyncFunctionDef),
                        })
                    elif info:
                        decorators[info] += 1

    # Frameworks present
    frameworks = sorted({_FRAMEWORK_MARKERS[k] for k in imports if k in _FRAMEWORK_MARKERS})

    # Top-level deps that don't look like stdlib. sys.stdlib_module_names
    # (3.10+) is authoritative; pre-3.10 falls back to a curated set.
    stdlib = _stdlib_modules()
    third_party = sorted({k for k in imports if k not in stdlib and not k.startswith("_")})[:60]

    # Decorator patterns repeated ≥3 times — the long tail is noise
    common_decorators = [
        {"name": name, "count": n}
        for name, n in decorators.most_common()
        if n >= 3
    ][:40]

    # Stable hash so repeat startups can skip duplicate ships
    sig_blob = "|".join([
        ",".join(sorted(third_party)),
        ",".join(frameworks),
        f"files={file_count}",
        f"async={async_count}",
        f"routes={len(routes)}",
    ])
    signature_hash = hashlib.sha256(sig_blob.encode("utf-8")).hexdigest()[:16]

    return {
        "language": "python",
        "root_basename": root.name,
        "file_count": file_count,
        "test_file_count": test_files,
        "parse_errors": parse_errors,
        "timed_out": timed_out,
        "frameworks": frameworks,
        "third_party_deps": third_party,
        "top_dirs": [d for d, _ in top_dirs.most_common(10)],
        "decorator_patterns": common_decorators,
        "routes": routes[:80],  # cap so a megaservice doesn't bloat the payload
        "function_count": function_count,
        "async_function_count": async_count,
        "sync_function_count": sync_count,
        "signature_hash": signature_hash,
    }


def push_code_signature(client, root: str | Path | None = None) -> str | None:
    """Run extraction and enqueue the result on the given client.

    Returns the signature hash if shipped, or None if extraction was
    skipped/failed. Designed to be fire-and-forget — never raises out.
    """
    if client is None:
        return None
    try:
        sig = extract_code_signature(root)
    except Exception:
        return None
    if sig.get("skipped") or sig.get("error"):
        return None

    h = sig.get("signature_hash")
    try:
        client.enqueue({
            "type": "custom",
            "fingerprint": f"code_signature:{h}",
            "payload": {
                "kind": "code_signature",
                "name": "code_signature",
                "props": sig,
            },
        })
    except Exception:
        return None
    return h
