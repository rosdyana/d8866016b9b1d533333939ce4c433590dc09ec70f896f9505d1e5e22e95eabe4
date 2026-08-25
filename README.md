# ccscraper

Self-hosted scraper service that turns a URL into clean, structured output — raw HTML, Markdown, and boilerplate-stripped LLM-ready text — via a staged fallback pipeline that only escalates to a heavier (slower, more expensive) fetch strategy when the cheaper one in front of it fails.

## How it works

```
URL
 │
 ▼
Stage 0: robots.txt gate (cached per domain, fail-closed on fetch errors)
 │
 ▼
Stage 1: direct HTTP fetch          ──passes quality check──▶ Extract
 │ fails
 ▼
Stage 2: Playwright (headless Chromium, cookie/popup dismissal)  ──▶ Extract
 │ fails
 ▼
Stage 3: Playwright via proxy (stubbed, disabled by default)
 │ fails
 ▼
Stage 4: crawl4ai sidecar (last resort)   ──passes quality check──▶ Extract
 │ fails
 ▼
job status: "blocked"
```

A per-domain memory (Redis, 7-day TTL) remembers which stage last succeeded for a domain, so repeat requests skip straight past stages already known to fail for it.

## Requirements

- Docker + Docker Compose
- A real random token for `AUTH_TOKEN` and `CRAWL4AI_API_TOKEN`, e.g. `openssl rand -hex 32`

## Setup

1. `cp env.example .env` and fill in real values — `AUTH_TOKEN` and `CRAWL4AI_API_TOKEN` are both required (see comments in the file for why; `CRAWL4AI_API_TOKEN` isn't just security hardening, the crawl4ai sidecar is unreachable from the `worker` container without it).
2. `docker compose up --build`
3. The API is published on `127.0.0.1:${APP_PORT}` (default `8000`), not on all interfaces — it's meant to sit behind a reverse proxy, not be reached directly. Set `APP_PORT` in `.env` if `8000` is already taken by another service on the host.

### Reverse proxy (Caddy)

On a host already running Caddy in front of other services, add a site block pointing at the loopback port:

```caddyfile
scraper.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy handles TLS; the container itself is never exposed publicly.

## API

Every endpoint except `/healthz` requires `Authorization: Bearer <AUTH_TOKEN>`.

**Submit a job**

```
POST /jobs
{"url": "https://example.com/", "formats": ["raw_html", "markdown", "llm_text"]}
```

Returns `202 Accepted` with a job object (`id`, `status: "queued"`).

**Poll for the result**

```
GET /jobs/{id}
```

`status` is one of `queued`, `running`, `success`, `blocked`, `robots_disallowed`, `unsupported_content_type`, `timeout`, `error`. On `success`, `result` holds the requested output formats and `stage_won` names which stage produced them.

## Configuration

See `env.example` for the full list of environment variables (timeouts, concurrency caps, TTLs, feature flags). All are read by `app/config.py`.

## Development

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[api,worker,dev]"   # Windows; use .venv/bin/pip on Linux/macOS
.venv/Scripts/python -m playwright install chromium
.venv/Scripts/python -m pytest
```

Running the API and worker outside Docker needs a local Redis plus `AUTH_TOKEN`/`REDIS_URL` set (see `env.example`):

```bash
AUTH_TOKEN=dev-token REDIS_URL=redis://localhost:6379/0 .venv/Scripts/python -m uvicorn app.main:app --port 8000
AUTH_TOKEN=dev-token REDIS_URL=redis://localhost:6379/0 .venv/Scripts/python -m arq worker.main.WorkerSettings
```

## Project layout

- `app/` — FastAPI web tier (job submission/status only; never imports Playwright or a crawl4ai client)
- `worker/` — arq worker that actually executes the fallback pipeline
- `pipeline/` — the fetch stages, robots gate, browser pool, consent dismissal, domain memory
- `extract/` — canonical HTML → raw_html/markdown/llm_text formatting, decoupled from which stage won
- `common/` — logging, error types, per-domain rate limiting, HTTP headers
- `docker/` — separate Dockerfiles for the light `api` image and the Playwright-heavy `worker` image

## Known limitations / next steps

- **Stage 3 (Playwright via proxy) is a stub.** `PROXY_ENABLED=false` by default. Wire in a real proxy pool by implementing `pipeline/proxy/provider.py`'s `ProxyProvider` interface — nothing else needs to change.
- **Stage 4 (crawl4ai) needs a live check on first real deployment.** Its request/response handling is validated against crawl4ai's documented and source-verified behavior, but hasn't been exercised against a running crawl4ai container yet.
- **Cookie/popup dismissal is heuristic-based** (known CMP selectors + multilingual text matching + generic overlay hiding in `pipeline/consent/dismiss.py`), not a vendored copy of a maintained consent-rules library. It degrades gracefully but won't catch every CMP design.
