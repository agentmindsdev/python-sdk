"""agentminds CLI — `agentminds connect` is the one-command onboarding
that registers the site and wires the SDK in a single step.

Why a CLI: dashboard install snippets work for someone who reads docs
top-to-bottom. The CLI works for someone who has 30 seconds.

Usage:
  agentminds connect [--url=...] [--email=...] [--name=...] [--root=PATH]
      Register the site against the API + auto-apply SDK install in one go.
      The recommended end-to-end install path: pip install agentminds && agentminds connect.

  agentminds setup [--dsn=...] [--apply] [--root=PATH]
      Lower-level: framework detection + prints/applies install steps for
      a DSN you already have.

  agentminds version

The CLI is intentionally tiny — argparse + stdlib urllib, no extra deps.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# ── ANSI helpers (no colorama dep — POSIX/Win10+ both render these) ─────

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

# Some Windows consoles (cp1254 / cp1252) can't encode → … ✓ etc., which
# crashes prints with UnicodeEncodeError. Detect that up-front and pick
# an ASCII-safe glyph set so we never crash on a happy-path message.
def _can_encode(s: str) -> bool:
    enc = getattr(sys.stdout, "encoding", None) or ""
    if enc.lower().replace("-", "") in ("utf8", "utf16", "utf32"):
        return True
    try:
        s.encode(enc or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


_UNICODE_OK = _can_encode("→…✓")

ARROW = "→" if _UNICODE_OK else "->"
ELLIPSIS = "…" if _UNICODE_OK else "..."
CHECK = "✓" if _UNICODE_OK else "[ok]"


def _c(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _USE_COLOR else text


def _bold(t: str) -> str: return _c("1", t)
def _green(t: str) -> str: return _c("32", t)
def _yellow(t: str) -> str: return _c("33", t)
def _blue(t: str) -> str: return _c("34", t)
def _dim(t: str) -> str: return _c("2", t)


# ── Framework detection ─────────────────────────────────────────────────

# Marker files we look at to infer the project's framework. Order matters —
# we pick the first match.
_FRAMEWORK_MARKERS = [
    ("fastapi", [
        # `^fastapi(\b|[><=~!]|$)` — match bare name OR with version specifier
        ("text", r"^fastapi(\b|[><=~!]|$)", "requirements.txt"),
        ("text", r'"fastapi"', "pyproject.toml"),
        ("text", r"^fastapi(\b|$)", "Pipfile"),
    ]),
    ("flask", [
        ("text", r"^[Ff]lask(\b|[><=~!]|$)", "requirements.txt"),
        ("text", r'"[Ff]lask"', "pyproject.toml"),
    ]),
    ("django", [
        ("text", r"^[Dd]jango(\b|[><=~!]|$)", "requirements.txt"),
        ("text", r'"[Dd]jango"', "pyproject.toml"),
        ("file_exists", "manage.py", None),
    ]),
]


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def detect_framework(root: Path) -> str | None:
    for name, checks in _FRAMEWORK_MARKERS:
        for kind, pattern, filename in checks:
            if kind == "file_exists":
                if (root / pattern).exists():
                    return name
            elif kind == "text":
                p = root / filename
                if not p.exists():
                    continue
                content = _read(p)
                if re.search(pattern, content, re.MULTILINE):
                    return name
    return None


# ── Entry-file detection ───────────────────────────────────────────────

# Common locations; first match wins. Looking for files that instantiate
# the app object — the place where init() must run and middleware must
# attach.
_ENTRY_CANDIDATES = [
    "api/app.py", "api/main.py",
    "app/main.py", "app/app.py",
    "src/main.py", "src/app.py",
    "main.py", "app.py", "server.py", "asgi.py", "wsgi.py",
]

# Regexes that identify the framework instantiation line we want to
# anchor the inserts on.
_FASTAPI_INST_RE = re.compile(r"^(\s*)([\w]+)\s*=\s*FastAPI\s*\(", re.MULTILINE)
_FLASK_INST_RE = re.compile(r"^(\s*)([\w]+)\s*=\s*Flask\s*\(", re.MULTILINE)


def detect_entry_file(root: Path, framework: str) -> Path | None:
    """Find the file that instantiates the app object."""
    inst_re = _FASTAPI_INST_RE if framework == "fastapi" else _FLASK_INST_RE if framework == "flask" else None
    if inst_re is None:
        return None  # django doesn't follow this pattern

    for rel in _ENTRY_CANDIDATES:
        p = root / rel
        if p.exists() and inst_re.search(_read(p)):
            return p

    # Fallback: scan two levels deep
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        if sub.name in {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build"}:
            continue
        for p in sub.glob("*.py"):
            if inst_re.search(_read(p)):
                return p
        for p in sub.glob("*/*.py"):
            if inst_re.search(_read(p)):
                return p
    return None


# ── Snippet generators ──────────────────────────────────────────────────

def _fastapi_init_block(dsn_var: str = "AGENTMINDS_DSN") -> str:
    return (
        "import os\n"
        "import agentminds\n"
        "from agentminds.integrations.fastapi_app import AgentMindsMiddleware\n"
        "\n"
        "agentminds.init(\n"
        f"    dsn=os.environ.get(\"{dsn_var}\"),\n"
        "    environment=\"production\",\n"
        ")\n"
    )


def _flask_init_block(dsn_var: str = "AGENTMINDS_DSN") -> str:
    return (
        "import os\n"
        "import agentminds\n"
        "from agentminds.integrations.flask_app import init_app as agentminds_init_app\n"
        "\n"
        "agentminds.init(\n"
        f"    dsn=os.environ.get(\"{dsn_var}\"),\n"
        "    environment=\"production\",\n"
        ")\n"
    )


# ── File mutation (only with --apply) ───────────────────────────────────


def _has_agentminds_init(content: str) -> bool:
    """Cheap check — already wired up?"""
    return bool(re.search(r"agentminds\.init\s*\(", content))


def _splice_fastapi(content: str) -> str | None:
    """Insert init block above `app = FastAPI(` and middleware below it.

    Returns the modified content, or None if the file didn't match the
    expected shape (caller falls back to print-only).
    """
    if _has_agentminds_init(content):
        return None  # already there
    m = _FASTAPI_INST_RE.search(content)
    if not m:
        return None
    indent = m.group(1)
    var = m.group(2)
    # Find end-of-line for `app = FastAPI(...)` — could span lines if it has args
    end_paren = content.find(")", m.end())
    if end_paren == -1:
        return None
    end_line = content.find("\n", end_paren)
    if end_line == -1:
        end_line = len(content)

    init_block = _fastapi_init_block()
    middleware_line = f"{indent}{var}.add_middleware(AgentMindsMiddleware)\n"

    # Insert init block at top of file (after any __future__ imports / module docstring)
    insertion_point = _post_module_header(content)
    new = (
        content[:insertion_point]
        + init_block
        + "\n"
        + content[insertion_point:end_line + 1]
        + middleware_line
        + content[end_line + 1:]
    )
    return new


def _splice_flask(content: str) -> str | None:
    if _has_agentminds_init(content):
        return None
    m = _FLASK_INST_RE.search(content)
    if not m:
        return None
    indent = m.group(1)
    var = m.group(2)
    end_paren = content.find(")", m.end())
    if end_paren == -1:
        return None
    end_line = content.find("\n", end_paren)
    if end_line == -1:
        end_line = len(content)

    init_block = _flask_init_block()
    init_call = f"{indent}agentminds_init_app({var})\n"

    insertion_point = _post_module_header(content)
    new = (
        content[:insertion_point]
        + init_block
        + "\n"
        + content[insertion_point:end_line + 1]
        + init_call
        + content[end_line + 1:]
    )
    return new


def _post_module_header(content: str) -> int:
    """Return the index AFTER the module's docstring + __future__ imports.
    Anything we insert above that breaks syntax."""
    pos = 0
    # Skip shebang
    if content.startswith("#!"):
        pos = content.find("\n", pos) + 1
    # Skip module docstring
    stripped = content[pos:].lstrip()
    if stripped.startswith('"""') or stripped.startswith("'''"):
        quote = stripped[:3]
        offset = pos + (len(content[pos:]) - len(stripped))
        end = content.find(quote, offset + 3)
        if end != -1:
            pos = content.find("\n", end + 3) + 1
    # Skip __future__ imports + leading blank lines
    while pos < len(content):
        line_end = content.find("\n", pos)
        line = content[pos:line_end if line_end != -1 else None]
        stripped_line = line.strip()
        if (stripped_line.startswith("from __future__")
                or stripped_line == ""
                or stripped_line.startswith("#")):
            if line_end == -1:
                break
            pos = line_end + 1
        else:
            break
    return pos


# ── Top-level commands ─────────────────────────────────────────────────


def cmd_setup(args: argparse.Namespace) -> int:
    root = Path(args.root or os.getcwd()).resolve()
    if not root.is_dir():
        print(f"{_c('31', 'error')}: {root} is not a directory")
        return 2

    print()
    print(_bold("agentminds setup"))
    print(_dim(f"  scanning: {root}"))

    framework = detect_framework(root)
    if not framework:
        print()
        print(_yellow("Could not detect a Python framework."))
        print("Looked for fastapi / flask / django markers in requirements.txt, pyproject.toml, manage.py.")
        print()
        print("Either:")
        print(f"  • run from your project root: {_dim('cd /path/to/your-app && agentminds setup')}")
        print(f"  • or set --root explicitly: {_dim('agentminds setup --root=/path/to/your-app')}")
        return 1

    print(f"  framework: {_green(framework)}")

    entry = detect_entry_file(root, framework)
    if entry:
        print(f"  entry file: {_green(str(entry.relative_to(root)))}")
    else:
        print(f"  entry file: {_yellow('not auto-detected')}")

    dsn = args.dsn or os.environ.get("AGENTMINDS_DSN", "")
    if not dsn:
        print()
        print(_yellow("DSN missing."))
        print("Sign up at https://agentminds.dev/onboard, then re-run with:")
        print(_dim('  agentminds setup --dsn="https://pk_yoursite_xxx@api.agentminds.dev/yoursite_id"'))
        print(_dim("  or set AGENTMINDS_DSN=... in your shell"))
        return 1

    print(f"  dsn: {_green(_redact_dsn(dsn))}")
    print()

    # Print install steps
    if framework == "fastapi":
        _print_fastapi_steps(entry, dsn, root)
    elif framework == "flask":
        _print_flask_steps(entry, dsn, root)
    elif framework == "django":
        _print_django_steps(root)

    print()
    print(_bold("Add to your runtime environment (DON'T commit):"))
    print(f'  {_blue("AGENTMINDS_DSN")}={dsn}')
    print()

    # Optionally apply
    if args.apply and entry and framework in ("fastapi", "flask"):
        return _apply_to_entry(entry, framework)
    if args.apply and not entry:
        print(_yellow("--apply requires an auto-detected entry file. Skipped."))
        return 1

    print(_dim("Re-run with --apply to edit the entry file in place "
              "(a .agentminds.bak backup is created first)."))
    return 0


def _redact_dsn(dsn: str) -> str:
    # Redact secret part — leave site_id visible at the end
    import re as _re
    m = _re.match(r"(https://)([^@]+)(@.*)", dsn)
    if not m:
        return dsn
    user = m.group(2)
    redacted = user[:8] + ELLIPSIS + user[-4:] if len(user) > 16 else ELLIPSIS
    return f"{m.group(1)}{redacted}{m.group(3)}"


def _print_fastapi_steps(entry: Path | None, dsn: str, root: Path) -> None:
    rel = str(entry.relative_to(root)) if entry else "your FastAPI entry file"
    print(_bold(f"FastAPI install — 3 edits in {rel}:"))
    print()
    print(_blue("1)  At the TOP of the file (above any FastAPI() call):"))
    for line in _fastapi_init_block().rstrip("\n").split("\n"):
        print(f"    {line}")
    print()
    print(_blue("2)  Right BELOW your existing app = FastAPI(...):"))
    print(f"    app.add_middleware(AgentMindsMiddleware)")
    print()
    print(_blue("3)  Add to requirements.txt (or pyproject.toml):"))
    print(f"    agentminds>=0.4.1")


def _print_flask_steps(entry: Path | None, dsn: str, root: Path) -> None:
    rel = str(entry.relative_to(root)) if entry else "your Flask entry file"
    print(_bold(f"Flask install — 3 edits in {rel}:"))
    print()
    print(_blue("1)  At the TOP of the file (above any Flask() call):"))
    for line in _flask_init_block().rstrip("\n").split("\n"):
        print(f"    {line}")
    print()
    print(_blue("2)  Right BELOW your existing app = Flask(...):"))
    print(f"    agentminds_init_app(app)")
    print()
    print(_blue("3)  Add to requirements.txt (or pyproject.toml):"))
    print(f"    agentminds>=0.4.1")


def _print_django_steps(root: Path) -> None:
    print(_bold("Django install:"))
    print()
    print(_blue("1)  In manage.py / wsgi.py / asgi.py (whichever runs at startup):"))
    print()
    print("    import os")
    print("    import agentminds")
    print()
    print('    agentminds.init(')
    print('        dsn=os.environ.get("AGENTMINDS_DSN"),')
    print('        environment="production",')
    print('    )')
    print()
    print(_blue("2)  Add to requirements.txt:"))
    print("    agentminds>=0.4.1")
    print()
    print(_yellow("Note:"), "Django middleware integration is on the SDK roadmap. Today the init() above")
    print("       captures uncaught exceptions, threading errors, and ERROR-level logs.")


def _apply_to_entry(entry: Path, framework: str) -> int:
    content = _read(entry)
    if not content:
        print(_yellow(f"--apply: could not read {entry}. Aborted."))
        return 1
    if framework == "fastapi":
        new = _splice_fastapi(content)
    else:
        new = _splice_flask(content)
    if new is None:
        if _has_agentminds_init(content):
            print(_green(f"--apply: {entry.name} already has agentminds.init(). No change."))
            return 0
        print(_yellow(f"--apply: couldn't find an instantiation pattern in {entry}. Skipped."))
        return 1
    backup = entry.with_suffix(entry.suffix + ".agentminds.bak")
    shutil.copyfile(entry, backup)
    entry.write_text(new, encoding="utf-8")
    print(_green(f"--apply: edited {entry} (backup: {backup.name})"))
    return 0


# ── connect: one-command onboarding ────────────────────────────────────

# The onboarding endpoint. Override-able via env for self-hosted setups
# and tests; defaults to production.
_ONBOARD_API = os.environ.get("AGENTMINDS_API", "https://api.agentminds.dev").rstrip("/")
_ONBOARD_PATH = "/api/v1/sync/onboard"


def _prompt(label: str, default: str = "", required: bool = False) -> str:
    """Prompt the user for a value. EOF on stdin aborts the CLI immediately
    so a piped/non-interactive invocation can't infinite-loop."""
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            value = input(f"{label}{suffix}: ").strip()
        except EOFError:
            print()
            print(_yellow(f"  No input for {label}. Pass it as a flag (e.g. --url=...) or run interactively."))
            raise SystemExit(2)
        if not value and default:
            return default
        if value or not required:
            return value
        print(_yellow(f"  {label} is required."))


def _looks_like_url(s: str) -> bool:
    try:
        u = urlparse(s if "://" in s else f"https://{s}")
        return bool(u.netloc) and "." in u.netloc
    except Exception:
        return False


def _looks_like_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s))


def _normalize_url(s: str) -> str:
    if "://" not in s:
        s = f"https://{s}"
    return s.rstrip("/")


def _derive_name_from_url(url: str) -> str:
    """yourapp.com -> Yourapp; api.example.com -> Example."""
    netloc = urlparse(url).netloc.split(":")[0]
    parts = [p for p in netloc.split(".") if p not in ("www", "app", "api", "staging", "dev")]
    base = parts[0] if parts else netloc
    return base[:1].upper() + base[1:]


def _post_onboard(url: str, name: str, email: str) -> dict:
    """POST to onboarding endpoint, return parsed JSON or raise.

    Uses urllib so we don't drag a `requests` runtime dep into the SDK.
    """
    body = json.dumps({"url": url, "name": name, "email": email}).encode("utf-8")
    req = urllib.request.Request(
        _ONBOARD_API + _ONBOARD_PATH,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Server returned non-2xx — try to surface its message
        try:
            payload = json.loads(e.read().decode("utf-8"))
            detail = payload.get("detail") or payload.get("message") or str(payload)
        except Exception:
            detail = e.reason
        raise RuntimeError(f"onboard {e.code}: {detail}") from e


def _build_dsn(api_key: str, site_id: str) -> str:
    host = urlparse(_ONBOARD_API).netloc or "api.agentminds.dev"
    return f"https://{api_key}@{host}/{site_id}"


def cmd_connect(args: argparse.Namespace) -> int:
    root = Path(args.root or os.getcwd()).resolve()
    if not root.is_dir():
        print(f"{_c('31', 'error')}: {root} is not a directory")
        return 2

    print()
    print(_bold("agentminds connect"))
    print(_dim(f"  scanning: {root}"))

    # ── Resolve url / email / name (flags > prompts) ──────────────────
    url = (args.url or "").strip()
    email = (args.email or "").strip()
    name = (args.name or "").strip()

    is_tty = sys.stdin.isatty()

    if not url:
        if not is_tty:
            print(_yellow("--url is required when running non-interactively."))
            return 2
        url = _prompt("Site URL (e.g. yourapp.com)", required=True)
    if not _looks_like_url(url):
        print(_yellow(f"That doesn't look like a URL: {url!r}"))
        return 2
    url = _normalize_url(url)

    if not email:
        if not is_tty:
            print(_yellow("--email is required when running non-interactively."))
            return 2
        email = _prompt("Email (so we can recover your key)", required=True)
    if not _looks_like_email(email):
        print(_yellow(f"That doesn't look like an email: {email!r}"))
        return 2

    if not name:
        name = _derive_name_from_url(url)
        if is_tty:
            name = _prompt("Site name", default=name)

    print()
    print(f"  url:   {_green(url)}")
    print(f"  email: {_green(email)}")
    print(f"  name:  {_green(name)}")
    print()

    # ── Register site ─────────────────────────────────────────────────
    print(_dim(f"{ARROW} registering with " + _ONBOARD_API + " ..."))
    try:
        result = _post_onboard(url, name, email)
    except RuntimeError as e:
        print()
        print(_yellow(f"Registration failed: {e}"))
        print(_dim("If you already registered this site, recover the key at https://agentminds.dev/onboard"))
        return 1
    except urllib.error.URLError as e:
        print()
        print(_yellow(f"Could not reach AgentMinds API: {e.reason}"))
        print(_dim("Check your internet connection, or set AGENTMINDS_API=... for a self-hosted install."))
        return 1

    api_key = result.get("api_key")
    site_id = result.get("site_id")
    if not (api_key and site_id):
        print(_yellow(f"Unexpected response from server: {result!r}"))
        return 1

    dsn = _build_dsn(api_key, site_id)
    print(_green(f"{CHECK} registered"))
    print(f"  site_id: {_green(site_id)}")
    print(f"  dsn:     {_green(_redact_dsn(dsn))}")

    if result.get("first_scan"):
        fs = result["first_scan"]
        grade = fs.get("grade") or "?"
        issues = fs.get("issue_count")
        bits = [f"grade {grade}"]
        if issues is not None:
            bits.append(f"{issues} surface issue(s)")
        print(f"  first scan: {_dim(', '.join(bits))}")

    print()

    # ── Detect framework + apply ──────────────────────────────────────
    framework = detect_framework(root)
    if not framework:
        print(_yellow("Could not auto-detect a Python framework in this directory."))
        print(_dim("If your project lives elsewhere, re-run with --root=/path/to/your-app"))
        print(_dim("Otherwise, here's how to wire it up manually:"))
        _print_django_steps(root)
        _print_env_var(dsn)
        return 0

    print(f"  framework: {_green(framework)}")
    entry = detect_entry_file(root, framework)
    if entry:
        print(f"  entry file: {_green(str(entry.relative_to(root)))}")
    else:
        print(f"  entry file: {_yellow('not auto-detected')}")
    print()

    if framework == "fastapi":
        _print_fastapi_steps(entry, dsn, root)
    elif framework == "flask":
        _print_flask_steps(entry, dsn, root)
    elif framework == "django":
        _print_django_steps(root)

    # Apply by default (this is "connect" — the one-command flow)
    if entry and framework in ("fastapi", "flask") and not args.no_apply:
        print()
        rc = _apply_to_entry(entry, framework)
        if rc != 0:
            print(_dim("Edit failed — apply the steps above manually."))

    _print_env_var(dsn)
    print(_bold("Next:"))
    print("  1) Set the env var above in your runtime (Render / Vercel / Docker / .env).")
    print("  2) Deploy — your site is now sending reports to the network.")
    print(f"  3) Visit https://agentminds.dev/dashboard?site={site_id} to see your data.")
    print()
    return 0


def _print_env_var(dsn: str) -> None:
    print()
    print(_bold("Add to your runtime environment (DON'T commit):"))
    print(f'  {_blue("AGENTMINDS_DSN")}={dsn}')


def cmd_version(args: argparse.Namespace) -> int:
    from . import __version__
    print(__version__)
    return 0


# ── Entry point ─────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="agentminds",
        description="AgentMinds CLI — wire the SDK into your app",
    )
    sub = p.add_subparsers(dest="cmd")

    connect = sub.add_parser(
        "connect",
        help="Register this site + auto-apply SDK install in one step",
    )
    connect.add_argument("--url", help="Your site URL (e.g. https://yourapp.com). Prompted if omitted.")
    connect.add_argument("--email", help="Email for key recovery. Prompted if omitted.")
    connect.add_argument("--name", help="Site name. Defaults to a guess from the URL.")
    connect.add_argument("--root", help="Project root to scan. Defaults to cwd.")
    connect.add_argument("--no-apply", action="store_true", help="Don't edit the entry file — just print steps.")
    connect.set_defaults(func=cmd_connect)

    setup = sub.add_parser("setup", help="(advanced) Detect framework, print/apply install for an existing DSN")
    setup.add_argument("--dsn", help="DSN string. Falls back to $AGENTMINDS_DSN.")
    setup.add_argument("--apply", action="store_true", help="Edit the entry file in place (creates .agentminds.bak backup)")
    setup.add_argument("--root", help="Project root to scan. Defaults to cwd.")
    setup.set_defaults(func=cmd_setup)

    ver = sub.add_parser("version", help="Print SDK version")
    ver.set_defaults(func=cmd_version)

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
