# Changelog

All notable changes to the `agentminds` Python SDK are documented here.

## [Unreleased]

## [0.5.0] — 2026-05-08

Minor release. Backwards compatible.

### Added
- **`agentminds.sync` module** — high-level helpers for the
  AgentMinds `/sync` API surface so integrators never hand-roll JSON
  payloads or manage the `X-AgentMinds-Key` header by hand.
  - **Push (your data → AgentMinds):** `sync.report(api_key,
    site_id, agent, metrics, warnings, learned_patterns,
    project_info)` posts a structured agent report to
    `/api/v1/sync/bulk`.
  - **Pull (AgentMinds insights → your code):**
    `sync.recommendations(api_key, limit=...)`,
    `sync.benchmarks(api_key, site_id)`,
    `sync.my_role(api_key)`,
    `sync.network_position(api_key)`,
    `sync.issues(api_key, status="open")`. All return parsed JSON;
    no manual `requests` / header plumbing.
- **`agentminds.metrics` module** — canonical metric emitters that
  mirror the server-side registry. Lets a Python app push metrics by
  the same names the central pool uses (`hsts_present`,
  `ssl_days_remaining`, `bounce_rate`, etc.) without hand-coding
  the schema. Avoids the "your push got grade-D because metric
  names didn't match" failure mode.

### Changed
- README rewritten around the **cross-site collective intelligence**
  positioning: the SDK pushes runtime events + agent reports into a
  shared pool and pulls personalized recommendations back. Install
  steps unchanged; the framing leads with the network value rather
  than the captured-events value.
- `pyproject.toml` metadata expanded:
  - 6 URL entries in `[project.urls]` — Homepage, Documentation,
    Repository, Issues, Changelog, Spec.
  - `Spec` link now points at `agentmindsdev/profile` (the public
    ARP spec repo, CC-BY-4.0).
  - `keywords` extended for collective-intelligence / ai-agents
    discoverability on PyPI.

### Compatibility
- Compatible with AgentMinds backend `a8c23b3+` (tier-aware
  shaping: `/sync/trial-rules`, `/sync/personalized-rules`).
- Compatible with `agentminds-mcp 1.3.0+`.
- Implements the response-shape contract published in
  [ARP spec v1.3.0](https://github.com/agentmindsdev/profile)
  (`top_production_observed` + `top_documented` split arrays,
  `negative_evidence`, optional `reversibility` field — passed
  through unchanged from server response, no client-side parsing
  required).
- Python `>=3.8` supported.

### Internal
- Test suite at 83 tests (pytest), all passing.
- 0 Turkish characters in `.py` / `.toml` / `.cfg` / `.md` source
  files (English-only contract aligned with the company-wide
  user-facing strings rule).
- `python -m build --sdist` verified clean (hatchling backend,
  isolated venv).

## [0.4.2] — 2026-04-27

### Fixed
- **`agentminds: command not found` on Windows.** Pip installs the
  binary in `<python>/Scripts/` which is NOT on PATH for `--user`
  installs by default — a fresh stranger running
  `pip install agentminds && agentminds connect` would get
  command-not-found even though install succeeded. Discovered when a
  real onboarding attempt failed silently in this exact way.

  Fix: added `agentminds/__main__.py` so `python -m agentminds
  connect` works as the canonical entry point. The Python interpreter
  the user just used to run `pip` is always on PATH, so this form
  works regardless of `Scripts/` PATH state.

  All website + README install snippets now lead with the
  `python -m agentminds` form. The bare `agentminds` console script
  still ships and still works for users whose `Scripts/` IS on PATH.

## [0.4.1] — 2026-04-26

### Fixed
- **Crash on Windows non-UTF8 consoles.** `agentminds connect` was
  crashing with `UnicodeEncodeError: 'charmap' codec can't encode
  character '→'` on cp1254 (Turkish) and cp1252 (Western)
  Windows consoles. The CLI now detects whether stdout can encode
  unicode glyphs and falls back to ASCII (`->`, `...`, `[ok]`) when
  it can't. Discovered via real smoke test against PyPI 0.4.0.
- Stale `agentminds>=0.2.1` reference in install snippets bumped to
  `agentminds>=0.4.1` so generated requirements lines pull in a
  version that actually has the `connect` command.

## [0.4.0] — 2026-04-26

### Added
- **`agentminds connect` — one-command onboarding.** New CLI subcommand
  that wraps the entire signup flow in a single shell command. Prompts
  for site URL + email (or accepts `--url` / `--email` flags), POSTs to
  `/api/v1/sync/onboard`, builds the DSN from the returned `api_key` and
  `site_id`, then auto-detects framework + applies the SDK install in
  place (FastAPI / Flask). End-state: `pip install agentminds &&
  agentminds connect` is the entire onboarding for a stranger.
- `AGENTMINDS_API` env var now overrides the onboarding endpoint host
  (used by self-hosted setups + tests). Defaults to
  `https://api.agentminds.dev`.
- 23 new pytest cases for the connect command's pure helpers (URL +
  email validation, URL normalization, name derivation, DSN format).

### Fixed
- `_prompt()` was infinite-looping when invoked with stdin closed.
  EOF on stdin now aborts with `SystemExit(2)` and a clear
  "pass it as a flag" hint.

### Why
- The previous flow was: register on agentminds.dev/onboard, copy the
  DSN out of the dashboard, run `agentminds setup --apply` separately.
  Three steps, two surfaces. `connect` collapses it into one — which is
  what the home page + /docs hero now promise.

## [0.3.0] — 2026-04-26

### Added
- **CLI installer.** `pip install agentminds` now ships an
  `agentminds` console script. `agentminds setup` auto-detects the
  host project's framework (FastAPI / Flask / Django) and prints
  exact-line instructions for where to add the init call, where to
  attach the middleware, what to put in requirements.txt, and what
  env var to set in production. Optional `--apply` edits the entry
  file in place after creating a `.agentminds.bak` backup.

### Why
- The dashboard install snippet works for someone who reads it
  carefully. The CLI works for someone who has 30 seconds and
  doesn't want to read at all. `agentminds setup` is what a
  stranger running `npm create-vite` or `npx create-next-app`
  would expect.

### What it does (zero-deps, no extra install step)
- Reads `requirements.txt` / `pyproject.toml` / `manage.py` to
  detect the framework. Walks common entry-file locations
  (`api/app.py`, `app/main.py`, `main.py`, etc.) to find the
  `app = FastAPI(…)` or `app = Flask(…)` line.
- Prints the install steps with the **actual file path** of the
  detected entry file so the user knows exactly where to paste.
- Redacts the DSN secret in console output (only shows the public
  prefix + the site_id at the end) — safe to show in screen
  recordings or pair-programming.
- Idempotent: if `agentminds.init(` is already in the file, exits
  cleanly with "no change".

### Subcommands
| Command | What it does |
|---|---|
| `agentminds setup` | Detect + print steps |
| `agentminds setup --apply` | Edit the entry file in place (backs up first) |
| `agentminds setup --dsn=...` | Override / supply the DSN |
| `agentminds setup --root=PATH` | Run against a project other than cwd |
| `agentminds version` | Print SDK version |

### Limitations called out
- Django: doesn't auto-edit `manage.py`; prints generic init steps
  (Django middleware integration is on the SDK roadmap).
- Custom entry-file layouts: if `app = FastAPI()` isn't auto-found,
  the CLI prints generic steps and skips `--apply`.

## [0.2.1] — 2026-04-26

Internal review pass on the 0.2.0 introspection feature — three small
correctness/perf fixes, no API changes.

### Fixed
- **Walk timeout actually enforced.** `SCAN_TIMEOUT_S` was declared in
  0.2.0 but the walk had no timeout check. Now the entire pass
  (file walk + parse loop) is capped by a `time.monotonic()` deadline.
  If the deadline trips mid-walk we return whatever was found so far
  and tag the result with `timed_out: True`. Init never blocks on a
  pathological project layout.
- **Stdlib detection uses `sys.stdlib_module_names`** when available
  (Python 3.10+). The hand-curated fallback for 3.8/3.9 was missing
  common modules (socket, signal, struct, gzip, decimal, …) which
  meant `third_party_deps` carried false positives. Net effect: the
  `third_party_deps` list now actually reflects third-party deps.
- **Backend `/sync/code-signature` history.** The SQL was
  `SELECT DISTINCT ON (hash) … LIMIT 30` ordered by hash, which gave
  the alphabetically-first 30 hashes instead of the 30 most-recent
  distinct stacks. Wrapped in an outer SELECT so we sort by
  `received_at DESC` after collapsing duplicates.

### Performance
- `function_names` was being collected as a list only to take its
  length at the end. Replaced with an integer counter — no behaviour
  change, drops O(n) memory on large codebases.

## [0.2.0] — 2026-04-26

### Added
- **Code introspection at init time** — `agentminds.init()` now walks the
  host app's codebase once at startup and ships a structured "code
  signature" so AgentMinds knows what it's monitoring without any
  follow-up step. No MCP, no cron, no manual push. One DSN, full
  picture: frameworks, routes, decorator patterns, third-party deps,
  function counts.

### What gets shipped (single `custom` event with `kind=code_signature`)
- Detected web frameworks (fastapi, flask, django, starlette, …) +
  observability + DB + LLM libs
- HTTP route handlers — method, path literal, handler name, async/sync
- Decorator patterns repeated ≥3 times across the codebase
- Top-level package layout (depth ≤6, file count caps)
- Third-party dependency list pulled from imports
- Async vs sync function ratio
- Test file count
- Stable `signature_hash` so repeat startups can short-circuit

### Privacy / safety
- Function bodies, docstrings, comments, and string literals are NEVER
  read or sent — only structural facts (names, decorators, route paths).
- Walk skips `.git`, `node_modules`, `.venv`, `dist`, build artifacts,
  third-party vendor dirs.
- Hard caps: 800 files, 200 KB per file, depth 6, parse errors swallowed.
- Best-effort: if introspection fails, init continues.
- Disable via `agentminds.init(introspect_code=False)` or override the
  scan root via `project_root="..."`.

## [0.1.0] — 2026-04-26

Initial public release.

### Added
- `agentminds.init(dsn=...)` — single entry point. Idempotent; no-op without DSN.
- Auto-capture for `sys.excepthook` and `threading.excepthook` (chains to existing handlers, never replaces).
- Logging integration — `ERROR` and above ship as events, `INFO` / `WARNING` become breadcrumbs that ride along with the next captured event.
- Manual capture API — `capture_exception`, `capture_message`, `capture_event`.
- Scope API — `set_user`, `set_tag`, `set_extra`, `set_transaction`, `add_breadcrumb`, `clear_scope`. Thread-local so concurrent requests don't bleed state.
- FastAPI integration — `agentminds.integrations.fastapi_app.AgentMindsMiddleware` (per-request scope reset + handler exception capture + 5xx capture).
- Flask integration — `agentminds.integrations.flask_app.init_app(app)` (`before_request` / `errorhandler(Exception)` / `after_request` hooks).
- Release auto-detection from `git rev-parse --short HEAD`.
- Background worker thread + bounded queue (1000 events, drop-oldest under back-pressure) so capture is O(1) on the hot path.
- `atexit` hook flushes on interpreter shutdown.

### Wire format
- Posts batched events to `POST {api_base}/api/v1/sync/ingest/{site_id}/events?key={public_key}` with body `{ "events": [...] }`. Identical envelope as the browser collector and the Node SDK — all three land in the same `runtime_events` table.

### Privacy defaults
- `send_default_pii=False` — no request bodies, no DB query parameters captured.
- Stack traces truncated to 8 KB; messages to 500 chars.
- User PII (email, IP) only sent if explicitly set via `set_user(...)`.
