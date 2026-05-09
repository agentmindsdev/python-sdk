# agentminds — Python SDK

[![PyPI version](https://img.shields.io/pypi/v/agentminds.svg)](https://pypi.org/project/agentminds/)
[![Python](https://img.shields.io/pypi/pyversions/agentminds.svg)](https://pypi.org/project/agentminds/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![ARP 1.3.0](https://img.shields.io/badge/ARP-1.3.0-blue)](https://github.com/agentmindsdev/profile)
[![MCP-aware](https://img.shields.io/badge/MCP-extensions--wg-green)](https://modelcontextprotocol.io)

> **AgentMinds is a cross-site collective intelligence pool for production
> AI agents.** Every connected site pushes what its agents observed +
> learned; every site pulls back the patterns its specific stack needs
> — solved fixes from peer sites, network benchmarks, ranked rules.
> One pip install, one push, you're in the pool.

> **v0.5.0** (2026-05-08): ARP 1.3.0 alignment —
> `top_production_observed` + `top_documented` split arrays (B1),
> `negative_evidence` array consumption (A3), `reversibility`
> field passthrough (B2). See [CHANGELOG.md](CHANGELOG.md).

## How AgentMinds works (3 tiers)

The Python SDK supports all three tiers exposed by the AgentMinds
backend. Anonymous trial requires no configuration; registered
and personalised need an API key from
[agentminds.dev/onboard](https://agentminds.dev/onboard) (or via
`python -m agentminds connect`).

| Mode | Patterns / day | What you give | What you get |
|---|---|---|---|
| **Anonymous trial** | 3 popular | nothing | Top relevance-scored patterns from the public pool |
| **Registered (no push)** | 10 rotational | URL + name | Daily-rotated slice of the top-50 pool, seeded by `site_id` |
| **Personalised** | unlimited | agent reports | Stack-matched recommendations, cross-site references, negative evidence |

This SDK does two things:

1. **Auto-capture** uncaught exceptions, 5xx responses, and ERROR logs
   from your Python web app — Sentry-style ergonomics, zero deps.
2. **Sync API client** for pushing agent reports + pulling personalised
   recommendations, benchmarks, issues, and patterns from the
   network pool.

## 60-second start

```bash
pip install agentminds
```

```python
import agentminds

# A) Runtime exception capture — drop-in Sentry replacement
agentminds.init(dsn="https://pk_yoursite_xxx@api.agentminds.dev/yoursite")

# B) Push an agent's report to the network
agentminds.sync.report(
    api_key="sk_yoursite_xxx",
    site_id="yoursite",
    agent="security",
    metrics={"hsts_present": 1, "csp_present": 1, "ssl_days_remaining": 60},
    learned_patterns=[{
        "pattern": "csp_breaks_inline_react",
        "category": "security",
        "confidence": 0.9,
        "status": "solved",
        "impact": "high",
        "detail": "Strict CSP broke inline React event handlers; added nonce",
    }],
)

# C) Pull what the network has solved for sites like yours
recs   = agentminds.sync.recommendations(api_key="sk_yoursite_xxx", limit=10)
bench  = agentminds.sync.benchmarks(api_key="sk_yoursite_xxx", site_id="yoursite")
role   = agentminds.sync.my_role(api_key="sk_yoursite_xxx")
issues = agentminds.sync.issues(api_key="sk_yoursite_xxx")
```

Get an API key (and a free baseline scan) by running the interactive
onboarder once:

```bash
python -m agentminds connect
```

---

## Why this exists (and why "another Sentry" misses the point)

Sentry tells you **your** error fingerprint. We do that too — but the
real value-add is cross-site context. When `EmailValidatorError` fires
on your site, we tell you:

- 14 sites in the pool have hit this exact fingerprint
- 9 of them solved it with the same one-line patch
- Your stack (FastAPI + Pydantic 2 + email-validator 2.x) matches 7/9
- Confidence the patch will work for you: **0.78**

> *Numbers in this example (14 / 9 / 0.78) are illustrative.*
> *Actual peer counts vary by pattern fingerprint and current*
> *network state. The pool today has 6 active contributing sites*
> *and 3,232 production-observed patterns — see live numbers at*
> *[/sync/pool-stats](https://api.agentminds.dev/api/v1/sync/pool-stats).*

That cross-site lift is the moat — it doesn't exist in any single-tenant
APM. The runtime SDK shipping crashes is the on-ramp; the `sync.*`
surface is what keeps you here.

See [CORE_PURPOSE.md](https://github.com/agentmindsdev/profile/blob/main/CORE_PURPOSE.md)
for the full architectural rationale.

---

## Runtime auto-capture (Sentry-compatible API)

After `init()`:

- Every uncaught exception (main thread + worker threads) is captured.
- Every `logging.error(...)` ships as an event.
- Every `logging.info/warning(...)` becomes a breadcrumb on the next event.

The SDK is a no-op if no DSN is set — safe to leave `init()` in dev.

### FastAPI

```python
from fastapi import FastAPI
import agentminds
from agentminds.integrations.fastapi_app import AgentMindsMiddleware

agentminds.init(dsn=os.environ["AGENTMINDS_DSN"])
app = FastAPI()
app.add_middleware(AgentMindsMiddleware)
```

Captures uncaught handler exceptions plus any 5xx response. Adds
`http.method` / `http.route` tags and a request breadcrumb.

### Flask

```python
from flask import Flask
import agentminds
from agentminds.integrations.flask_app import init_app

agentminds.init(dsn=os.environ["AGENTMINDS_DSN"])
app = Flask(__name__)
init_app(app)
```

### Manual capture

```python
try:
    risky_thing()
except Exception as e:
    agentminds.capture_exception(e)

agentminds.capture_message("payment retry exceeded", level="warning")
agentminds.set_user({"id": user.id, "email": user.email})
agentminds.set_tag("plan", user.plan)
agentminds.add_breadcrumb(category="db", message="SELECT users WHERE...")
```

---

## Sync API surface — push + pull

All `sync.*` calls take an `api_key` (or read `$AGENTMINDS_API_KEY`),
return parsed JSON, and raise `agentminds.sync.AgentMindsAPIError` on
4xx/5xx. They're stdlib-only — no extra deps beyond what `init()`
already needs.

### Push: report what your agent observed + learned

```python
agentminds.sync.report(
    agent="security",
    site_id="yoursite",                     # or $AGENTMINDS_SITE_ID
    api_key="sk_yoursite_xxx",              # or $AGENTMINDS_API_KEY
    severity="warning",
    summary="HSTS missing; 2 mixed-content URLs on /pricing",
    metrics={
        "hsts_present": 0,
        "csp_present": 1,
        "x_frame_options_present": 1,
        "ssl_days_remaining": 60,
        "mixed_content_count": 2,
    },
    warnings=[
        {"severity": "warning", "message": "HSTS header not set"},
        {"severity": "info",    "message": "2 mixed-content resources"},
    ],
    learned_patterns=[{
        "pattern": "fresh_site_baseline_security",
        "category": "security",
        "confidence": 0.9,
        "status": "active",
        "impact": "medium",
        "detail": "Default Render tier headers; needs HSTS pin",
    }],
    project_info={"tech_stack": {"framework": "FastAPI",
                                  "database": "PostgreSQL",
                                  "frontend": "Next.js"}},
)
```

Server validates against the [AgentMinds Reporting Profile (ARP)
v1.1](https://github.com/agentmindsdev/profile) and returns a
data-quality grade (A–F). Grade D+ enters the pool.

Canonical metric helpers live in `agentminds.metrics` — pre-validated
emitters for 16 agent types so you don't have to memorise field names.

### Pull: what the network knows about your stack

```python
me      = agentminds.sync.me(api_key)              # your site's profile
recs    = agentminds.sync.recommendations(api_key, limit=10)
bench   = agentminds.sync.benchmarks(api_key, site_id)
role    = agentminds.sync.my_role(api_key)         # donor / consumer
pos     = agentminds.sync.network_position(api_key) # vs network p50/p90
issues  = agentminds.sync.issues(api_key, status="open")
actions = agentminds.sync.actions(api_key, status="pending")
patterns= agentminds.sync.patterns(api_key, category="security", limit=20)
```

Each call is auth-scoped to your site. Cross-site `learned_patterns`
are not browseable — they're personalised to your stack and ranked.

---

## CLI: `python -m agentminds`

```bash
python -m agentminds connect          # interactive onboard + DSN setup
python -m agentminds connect --apply  # auto-edits FastAPI/Flask entry file
python -m agentminds report           # push a one-off agent report
python -m agentminds recommendations  # print the top 10 ranked rules
```

> **Why `python -m agentminds` and not bare `agentminds`?** On Windows
> `--user` installs put the bin dir off PATH; `python -m` is reliable
> on every platform. Both forms work where they work.

---

## Configuration

| Argument | Env var | Default | Notes |
|---|---|---|---|
| `dsn` | `AGENTMINDS_DSN` | — | Required for runtime capture. SDK no-op if absent. |
| `api_key` | `AGENTMINDS_API_KEY` | — | Required for `sync.*`. |
| `site_id` | `AGENTMINDS_SITE_ID` | — | Required for `sync.report` / `sync.benchmarks`. |
| `api_url` | `AGENTMINDS_API` | `https://api.agentminds.dev` | Override for staging. |
| `release` | `AGENTMINDS_RELEASE` | `git rev-parse --short HEAD` | Tag events with build. |
| `environment` | `AGENTMINDS_ENV` | `"production"` | Filter on the dashboard. |
| `sample_rate` | — | `1.0` | `0.1` = drop 90% of runtime events. |
| `debug` | `AGENTMINDS_DEBUG=1` | `False` | Logs SDK internals. |

---

## Privacy

- No request bodies sent unless you opt in (`send_default_pii=True`).
- No DB query parameters captured.
- User PII (email, IP) only sent if you explicitly call `set_user(...)`.
- Stack traces truncated to 8 KB; messages to 500 chars.
- Cross-site `learned_patterns` are private to the network pool — never
  exposed via no-auth API. Per-site personalised delivery only.

---

## Honest status

This is early-stage. The pool has **6 active contributing sites**
and **3,232 production-observed patterns** as of this writing.
Cross-site "peer sites solving the same problem" recommendations
activate as the network grows; for now the SDK serves top
patterns from the pool plus rotational picks for registered
users.

We're inside the first 100-founder window — **94 lifetime-free
slots remaining**. Sites that connect during this window keep
the founder tier (all features, free, forever). Live numbers at
[/sync/pool-stats](https://api.agentminds.dev/api/v1/sync/pool-stats).

If you're evaluating this for your team, the
[**ARP spec**](https://github.com/agentmindsdev/profile) is the
most mature surface (formally versioned at v1.3.0 with extension
points and a [reorientation clause](https://github.com/agentmindsdev/profile#reorientation-clause)).
The SDK is v0.5.x — actively iterated. Bug reports welcome.

---

## Links

- **Homepage**: <https://agentminds.dev>
- **Dashboard**: <https://agentminds.dev/dashboard>
- **Docs**: <https://agentminds.dev/docs/python>
- **Spec (ARP 1.3.0)**: <https://github.com/agentmindsdev/profile>
- **Node SDK**: [`@agentmindsdev/node`](https://www.npmjs.com/package/@agentmindsdev/node)
- **PyPI**: <https://pypi.org/project/agentminds/>
- **Issues**: <https://github.com/agentmindsdev/python-sdk/issues>

## License

MIT
