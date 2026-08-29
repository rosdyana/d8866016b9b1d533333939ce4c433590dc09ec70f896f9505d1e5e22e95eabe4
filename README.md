# ccscraper

Self-hosted scraper service that turns a URL into clean, structured output — raw HTML, Markdown, and boilerplate-stripped LLM-ready text — via a staged fallback pipeline that only escalates to a heavier (slower, more expensive) fetch strategy when the cheaper one in front of it fails.

Every stage presents a real browser's fingerprint, because the target workload is OEM product catalogues (Dell, Lenovo, HP, Acer) that are actively bot-protected. Where those pages ship schema.org `Product` data, it is parsed out of `ld+json` and prepended to the text formats as a table.

## How it works

```
URL
 │
 ▼
Stage 0: robots.txt gate (cached per domain, fail-closed on fetch errors)
 │
 ▼
Stage 1: curl_cffi — real browser TLS/JA3 + HTTP/2 fingerprint, no browser
 │        ~0.3s                     ──passes quality check──▶ Extract
 │ fails
 ▼
Stage 2: Camoufox — patched Firefox, fingerprint spoofed in C++ (not JS),
 │        ~3-14s, cookie/popup dismissal   ──▶ Extract
 │ fails
 ▼
Stage 3: SeleniumBase CDP Mode — Chromium over DevTools with no WebDriver
 │        ~10-25s, solves Turnstile/reCAPTCHA/hCaptcha   ──▶ Extract
 │ fails
 ▼
job status: "blocked"
```

Stage 1 is not merely an optimisation. Verified 2026-08-29: `hp.com` and `acer.com` kill the connection at the TLS/HTTP2 layer for a plain HTTP client — `HTTP/2 INTERNAL_ERROR`, or an HTTP/1.1 hang delivering zero bytes — regardless of `User-Agent`, and return a normal 200 to the identical request made with curl_cffi's `impersonate`. All four target vendors currently resolve at Stage 1.

A per-domain memory (Redis, 7-day TTL) remembers which stage last succeeded for a domain, so repeat requests skip straight past stages already known to fail for it.

## Requirements

- Docker + Docker Compose
- A real random token for `AUTH_TOKEN`, e.g. `openssl rand -hex 32`

## Setup

1. `cp env.example .env` and fill in real values — `AUTH_TOKEN` is required. Note `USER_AGENT` is used *only* for robots.txt matching; no stage sends it, because overriding a stage's generated identity is what would break its fingerprint.
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

`formats` defaults to all three if omitted. Add `"robotstxt": false` to skip the robots.txt permission check for that request — off by default; robots.txt is respected unless a caller explicitly opts out.

Returns `202 Accepted` with a job object (`id`, `status: "queued"`).

**Poll for the result**

```
GET /jobs/{id}
```

`status` is one of `queued`, `running`, `success`, `blocked`, `robots_disallowed`, `unsupported_content_type`, `timeout`, `error`. On `success`, `result` holds the requested output formats and `stage_won` names which stage produced them.

## Response cache

A successful scrape is cached for 30 days (`SCRAPE_CACHE_TTL_SECONDS`) under a hash of the whole
request body — `url` + `formats` + `robotstxt`. Repeat the same body and the result comes back
immediately: still `202 Accepted`, but with `"cached": true` and `"status": "success"` already
set, so a caller that just polls `GET /jobs/{id}` finishes on its first poll. Every job response
carries the `cache_key` its request maps to.

Because the key is the whole body, asking for a different set of `formats` is a different entry
and re-fetches. Only successes are cached — a `blocked` or `timeout` is usually transient, and
freezing one for 30 days would take the URL out of service for a month. A result larger than
`SCRAPE_CACHE_MAX_ENTRY_BYTES` is returned normally but not stored.

Add `"refresh": true` to the `POST /jobs` body to skip the cache and fetch again. The fresh
result replaces the cached one on success; a failed refetch leaves the existing entry alone.

**Manage it**

```
GET    /cache?cursor=0&limit=100   # metadata only, no page bodies; cursor 0 means end of scan
GET    /cache/{key}                # one entry, with its full result
DELETE /cache/{key}                # drop one entry -> 204, or 404 if unknown
DELETE /cache                      # drop everything -> {"deleted": n}
```

`GET /cache` never returns page bodies — metadata and body are stored as separate Redis keys
precisely so a listing doesn't drag megabytes of `raw_html` per row. `DELETE /cache` is scoped
to the cache's own key prefixes; job records and the arq queue share the same Redis database and
are left untouched. All four need the bearer token.

## MCP

The same service also speaks the Model Context Protocol, so an LLM app can fetch a page as a
tool call instead of driving the job API by hand. The endpoint is **Streamable HTTP at `/mcp`**
on the existing API container — same port, same reverse proxy, same `AUTH_TOKEN`:

```json
{
  "mcpServers": {
    "ccscraper": {
      "url": "https://scraper.example.com/mcp",
      "headers": { "Authorization": "Bearer <AUTH_TOKEN>" }
    }
  }
}
```

Two tools:

| Tool | Arguments | Returns |
| --- | --- | --- |
| `scrape` | `url`, `formats` (default `["llm_text"]`), `robotstxt` (default `true`), `refresh` (default `false`), `wait_seconds` (default `45`, 5-300) | `status`, `stage_won`, and the requested format fields |
| `get_scrape_result` | `job_id`, `wait_seconds` | the same shape |

`formats` defaults to `llm_text` alone rather than all three: `raw_html` is routinely megabytes,
and a tool result goes straight into a model's context.

`scrape` reads through the same response cache the REST API does, so a page fetched in the last
30 days comes back instantly; `refresh: true` bypasses that and fetches again. The cache
management endpoints are deliberately not exposed as tools — a model shouldn't be clearing the
service's cache.

`scrape` submits the same job the REST API does and waits for it, reporting MCP progress
notifications while it does. A page that resolves at Stage 1 comes back in well under a second;
one that escalates to a browser can take tens of seconds, and if `wait_seconds` runs out the
result comes back with `status` still `queued`/`running` and a `job_id` to hand to
`get_scrape_result`. The default of 45s sits under the timeout most MCP clients apply to a tool
call, so the common case returns content in one call.

Terminal failures (`blocked`, `robots_disallowed`, `unsupported_content_type`, `timeout`,
`error`) come back as data rather than as tool errors, because the model needs to tell them
apart — "robots.txt forbids this" and "every stage was detected" call for different next moves.

`MCP_ALLOWED_HOSTS` is the one setting the MCP endpoint adds. Left empty it turns off the SDK's
DNS-rebinding check, which is correct behind a reverse proxy that already controls the `Host`
header and is what the loopback-only port mapping above assumes. Set it (comma-separated,
`scraper.example.com,scraper.example.com:*`) if the container is ever reachable directly.

If you write your own MCP client and supply your own `httpx2.AsyncClient` to carry the
`Authorization` header, set a long read timeout on it (`timeout=httpx2.Timeout(30.0,
read=300.0)`) — the SDK only applies its own 300s read timeout to a client it created, and the
default 5s will abort a browser-stage fetch mid-flight.

## Configuration

See `env.example` for the full list of environment variables (timeouts, concurrency caps, TTLs, feature flags). All are read by `app/config.py`.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[api,worker,dev]"       # .venv/Scripts/pip on Windows
.venv/bin/python -m camoufox fetch                 # Stage 2's Firefox build (~200MB)
.venv/bin/python -m playwright install firefox     # only for the consent-dismissal tests
.venv/bin/python -m pytest
```

Live network tests are deselected by default. They are the only thing that
verifies the premise the pipeline exists for — that these stages are not
detected — so run them before trusting a change to any stage:

```bash
.venv/bin/python -m pytest -m live -v
```

They check both browser stages against `bot.sannysoft.com` and
`browserscan.net/bot-detection`, assert Stage 1 still defeats the TLS-layer
blocks on `hp.com`/`acer.com`, and drive Stage 3 through a real Cloudflare
Turnstile. Stage 3 falls back to plain headless on macOS/Windows (Xvfb is
Linux-only), so a local pass is the weaker configuration for that stage.
Stage 2 is headless everywhere on purpose — see `STAGE2_USE_XVFB` in
`env.example` for the measurement behind that.

Running the API and worker outside Docker needs a local Redis plus `AUTH_TOKEN`/`REDIS_URL` set (see `env.example`):

```bash
AUTH_TOKEN=dev-token REDIS_URL=redis://localhost:6379/0 .venv/Scripts/python -m uvicorn app.main:app --port 8000
AUTH_TOKEN=dev-token REDIS_URL=redis://localhost:6379/0 .venv/Scripts/python -m arq worker.main.WorkerSettings
```

## Project layout

- `app/` — FastAPI web tier (job submission/status plus the `/mcp` endpoint; never imports a stage or a browser library)
- `worker/` — arq worker that actually executes the fallback pipeline
- `pipeline/` — the fetch stages, robots gate, browser concurrency slots, consent dismissal, domain memory
- `extract/` — canonical HTML → raw_html/markdown/llm_text formatting plus ld+json product parsing, decoupled from which stage won
- `common/` — logging, error types, per-domain rate limiting
- `docker/` — separate Dockerfiles for the light `api` image and the browser-heavy `worker` image

## Known limitations / next steps

- **IP reputation is the ceiling, and there is no proxy support.** Dell and Lenovo run Akamai Bot Manager (`_abck`/`bm_sz` cookies), which scores the source IP independently of how good a fingerprint is. All traffic leaves one datacenter IP, so sustained volume will eventually be rate-limited or challenged no matter how well stages 1-3 impersonate a browser. `PER_DOMAIN_MAX_CONCURRENCY` and the domain memory are the available mitigations; residential proxies would be the actual fix, and both Camoufox and SeleniumBase accept a `proxy=` argument if that decision is revisited.
- **Stage 3 cannot always report an HTTP status.** SeleniumBase's CDP surface returns HTML without one, so the stage reconstructs it from `Network.responseReceived` events and falls back to `200` when no top-level document response was observed. When that happens, block detection rests on the text/marker heuristics alone.
- **`Product` ld+json is common on detail pages, rare on listing pages.** Of the vendor pages checked, only Lenovo's product pages carried it; Dell, HP and Acer listing pages ship only `BreadcrumbList`/`Corporation`. The table appears when the data is there and is silently omitted otherwise.
- **Cookie/popup dismissal is heuristic-based** (known CMP selectors + multilingual text matching + generic overlay hiding in `pipeline/consent/dismiss.py`), not a vendored copy of a maintained consent-rules library. It degrades gracefully but won't catch every CMP design.
