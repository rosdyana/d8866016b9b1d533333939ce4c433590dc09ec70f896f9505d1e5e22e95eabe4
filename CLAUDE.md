# ccscraper — notes for working in this codebase

Self-hosted scraper service with a staged fallback pipeline (direct HTTP → Playwright → Playwright-via-proxy (stubbed) → crawl4ai), producing raw HTML / Markdown / LLM-text output over an authenticated async-job HTTP API. See `README.md` for the product-level overview; this file is about working in the code.

## Architecture at a glance

- `app/` (FastAPI) only creates/reads job records and enqueues arq jobs — it must never import `pipeline.stages`, `playwright`, or a crawl4ai client. This keeps `docker/api.Dockerfile` free of the Playwright/Chromium dependency that `docker/worker.Dockerfile` carries.
- `worker/` (arq) owns all actual fetching. `worker/main.py` builds long-lived resources once at startup (httpx client, `BrowserContextPool`, `RobotsGate`, `DomainMemory`) and stores them on `ctx`; `worker/tasks.py` builds the per-job stage list from `ctx` and calls `pipeline.orchestrator.run_pipeline`.
- `pipeline/orchestrator.py` is the only place that decides stage escalation order. It consults `pipeline/domain_memory.py` to skip stages already known to fail for a domain, and treats `UnsupportedContentType` (raised by Stage 1 for non-HTML responses) as immediately terminal — never escalate a PDF/image to a browser, a browser can't turn it into HTML either.
- `extract/` is deliberately decoupled from which stage won. `extract/models.py` has zero heavy dependencies (safe for the `api` container to import, for response typing only); `extract/markdown.py`/`llm_text.py` pull in trafilatura and are worker-only.

## Load-bearing facts, verified against source — don't re-guess these

- **crawl4ai's Docker server (>=0.9.0) hard-rejects `magic` and `simulate_user`** in a per-request `crawler_config`, returning HTTP 400 (`UNTRUSTED_FORBIDDEN_FIELDS` in `crawl4ai/async_configs.py`). `remove_overlay_elements` and `remove_consent_popups` are separately allowlisted and are what `pipeline/stages/stage4_crawl4ai.py` actually sends. `tests/unit/test_stage4_crawl4ai.py::test_stage4_never_sends_fields_crawl4ai_rejects_over_the_network` guards this — don't add fields to that request body without checking crawl4ai's forbidden-fields list first, or every Stage 4 call will start silently 400ing.
- **`CRAWL4AI_API_TOKEN` is not optional.** Without it, crawl4ai's server binds to loopback only and is unreachable from the `worker` container over the Docker network — this is a functional requirement, not just security hardening.
- The crawl4ai image tag in `docker-compose.yml` is pinned deliberately (never `:latest`) — `extract/normalize.py::build_from_crawl4ai` and `stage4_crawl4ai.py`'s request/response handling are validated against that specific version's source, not just its docs (which have shown real lag — e.g. a stale `docker pull` example alongside updated prose).
- `pipeline/quality.py`'s visible-text heuristic runs HTML through `extract.html_cleaner.clean_html()` (strips `<script>`/`<style>`) before counting characters. Never measure text length against raw HTML directly — a SPA that embeds its real content as JSON inside an inline `<script>` (e.g. quotes.toscrape.com/js/) will otherwise look content-rich when it's actually an empty shell, and Stage 1 will wrongly "succeed" instead of escalating. This was a real bug caught via live testing, not a hypothetical.
- Challenge-marker matching (`_CHALLENGE_MARKERS` in `pipeline/quality.py`) only applies below `_MARKER_CHECK_MAX_TEXT_LEN` characters of visible text. A long-form article that happens to mention "captcha" (e.g. an article *about* web scraping) must not be flagged just for using the word — only short, boilerplate-heavy pages get marker-checked.
- robots.txt fetch failures (timeout/5xx) fail **closed** — treated as disallowed — rather than open, per the "respect robots.txt" requirement (`pipeline/robots/gate.py`). A 404 means allow-all (spec default); that's a different case from a fetch error and must stay that way.

## Testing

- `tests/unit/` — fast, no real network/browser: `respx` for HTTP mocking, small fake-Redis doubles for cache/store classes (see `FakeCache`/`FakeRedis` patterns already in the test files — reuse that shape rather than adding a new mocking library).
- `tests/integration/test_consent_dismiss.py` — runs a real headless Chromium via the `playwright_page` fixture in `tests/conftest.py`. That fixture exists on purpose instead of using `pytest-playwright`'s built-ins, which are sync-API only and would clash with this codebase's async-only Playwright usage. Fixtures simulating a CMP banner must include the actual removal JS a real CMP script would run (an `onclick` handler) — a static fixture with no script only proves a button got clicked, not that dismissal worked.
- Run everything: `.venv/Scripts/python -m pytest -q` (Windows) — needs `playwright install chromium` done once first.
- When testing the API/worker live (not just pytest), a sandboxed/CI shell's Docker daemon may be unreachable — fall back to running `uvicorn app.main:app` and `arq worker.main.WorkerSettings` directly against a local Redis (see README's Development section) rather than assuming `docker compose up` works everywhere.

## Conventions

- Async throughout — no sync Playwright/httpx/redis clients anywhere in `app/`, `worker/`, or `pipeline/`.
- No speculative abstraction: stages, error types, and config fields exist because something in the pipeline actually uses them today. If you add a new field or exception, wire it to real behavior in the same change rather than adding it "for later."
- Comments are rare and explain WHY (a non-obvious constraint, or a bug this code specifically avoids repeating) — never WHAT the code does.
