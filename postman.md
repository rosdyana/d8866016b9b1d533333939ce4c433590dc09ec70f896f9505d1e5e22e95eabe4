# ccscraper — API reference for Postman

Everything needed to build a Postman collection by hand. If you'd rather skip typing it in: once the API is running, **Import → Link** in Postman and point it at `http://localhost:8000/openapi.json` (or your deployed URL) — FastAPI serves a live OpenAPI 3.0 spec and Postman imports it directly into a full collection with schemas. The reference below is for building it manually or double-checking the auto-import.

## Suggested Postman environment variables

| Variable | Example value |
|---|---|
| `base_url` | `http://localhost:8000` (or `https://scraper.example.com` once behind Caddy) |
| `auth_token` | the value of `AUTH_TOKEN` in `.env` |
| `job_id` | set from the response of "Create Job", used by "Get Job" |
| `cache_key` | set from the `cache_key` field of any job response, used by the cache requests |

## Auth

Every endpoint except `Health` and `Ready` requires:

```
Authorization: Bearer {{auth_token}}
```

In Postman: set this per-request under **Authorization → Type: Bearer Token → Token: `{{auth_token}}`**, or add it once at the collection level so every request inherits it.

---

## 1. Health check

**GET** `{{base_url}}/healthz`

No auth required. Always returns 200 if the API process is up (doesn't check Redis).

**Response `200`**
```json
{ "status": "ok" }
```

---

## 2. Readiness check

**GET** `{{base_url}}/readyz`

No auth required. Pings Redis — use this to confirm the API can actually reach its dependencies, not just that the process is running.

**Response `200`**
```json
{ "status": "ready" }
```

**Response `5xx`** if Redis is unreachable.

---

## 3. Create a scrape job

**POST** `{{base_url}}/jobs`

**Headers**
```
Authorization: Bearer {{auth_token}}
Content-Type: application/json
```

**Body (raw, JSON)**
```json
{
  "url": "https://example.com/",
  "formats": ["raw_html", "markdown", "llm_text"],
  "robotstxt": true,
  "refresh": false
}
```

- `url` — required.
- `formats` — optional, defaults to `["markdown"]` if omitted: `raw_html` is routinely megabytes and most callers feed the result to a model. Any subset of `raw_html`/`markdown`/`llm_text` is valid, e.g. `["raw_html", "markdown", "llm_text"]` for all three.
- `robotstxt` — optional, defaults to `true`. Set to `false` to skip the robots.txt permission check entirely for this request (an explicit per-call opt-out for trusted/authenticated callers — use deliberately, not as a default).
- `refresh` — optional, defaults to `false`. Set to `true` to skip the 30-day response cache and fetch again. The fresh result replaces the cached one on success.

**Response `202 Accepted`**
```json
{
  "id": "74f499106ffa413197d238a9057c3ce6",
  "url": "https://example.com/",
  "formats": ["raw_html", "markdown", "llm_text"],
  "robotstxt": true,
  "status": "queued",
  "stage_won": null,
  "result": null,
  "error": null,
  "cache_key": "9c1e6f0b2a...",
  "cached": false,
  "created_at": "2026-08-25T04:16:18.185766Z",
  "updated_at": "2026-08-25T04:16:18.185766Z"
}
```

**Response `202 Accepted` — cache hit.** Still 202, so the status code never varies per request. The result is already there, and `cached` is `true`:

```json
{
  "id": "b83a0f5c17d24e1f9a5c2d8e4b7f6a03",
  "url": "https://example.com/",
  "formats": ["raw_html", "markdown", "llm_text"],
  "status": "success",
  "cached": true,
  "cache_key": "9c1e6f0b2a...",
  "stage_won": "stage1_curl_cffi",
  "result": { "markdown": "# Example Domain\n\n..." }
}
```

Add a **Tests** script here too, to capture the key for the cache requests:
```javascript
pm.environment.set("cache_key", pm.response.json().cache_key);
```

In Postman, add a **Tests** script on this request to auto-capture the id for the next call:
```javascript
const body = pm.response.json();
pm.environment.set("job_id", body.id);
```

**Response `401 Unauthorized`** — missing/invalid bearer token.
**Response `422 Unprocessable Entity`** — invalid/missing `url`, or a `formats` value outside `raw_html`/`markdown`/`llm_text`.

---

## 4. Get job status / result

**GET** `{{base_url}}/jobs/{{job_id}}`

**Headers**
```
Authorization: Bearer {{auth_token}}
```

**Response `200`** — shape is identical to the create response, `status`/`result`/`stage_won`/`error` reflect current state. Poll this until `status` is no longer `queued`/`running`.

`status` values:

| Status | Meaning |
|---|---|
| `queued` | accepted, waiting for a worker |
| `running` | a worker is actively processing it |
| `success` | done — `result` holds the requested formats, `stage_won` names which stage produced them (`stage1_curl_cffi`, `stage2_crawl4ai`, `stage3_camoufox`, `stage4_seleniumbase`, `stage5_firecrawl`) |
| `blocked` | every stage failed its quality/anti-bot check |
| `robots_disallowed` | robots.txt forbids fetching this URL |
| `unsupported_content_type` | the URL resolved to non-HTML (PDF, image, etc.) |
| `timeout` | the job exceeded its overall time budget |
| `error` | an unexpected failure — see `error` field |

**Example — success:**
```json
{
  "id": "74f499106ffa413197d238a9057c3ce6",
  "url": "https://example.com/",
  "formats": ["raw_html", "markdown", "llm_text"],
  "status": "success",
  "stage_won": "stage1_curl_cffi",
  "result": {
    "raw_html": "<html>...</html>",
    "markdown": "# Example Domain\n\n...",
    "llm_text": "Example Domain\n..."
  },
  "error": null,
  "created_at": "2026-08-25T04:16:18.185766Z",
  "updated_at": "2026-08-25T04:16:18.791624Z"
}
```

**Example — blocked/failed:**
```json
{
  "id": "...",
  "status": "robots_disallowed",
  "stage_won": null,
  "result": null,
  "error": "robots.txt disallows fetching https://example.com/private"
}
```

**Response `401 Unauthorized`** — missing/invalid bearer token.
**Response `404 Not Found`** — unknown or expired `job_id` (results expire after `JOB_RESULT_TTL_SECONDS`, default 3 days).

---

## 5. List cache entries

**GET** `{{base_url}}/cache?cursor=0&limit=100`

Metadata only — page bodies are stored under separate Redis keys so a listing never drags megabytes of `raw_html` per row. Use `GET /cache/{{cache_key}}` to read one entry's content.

**Query params**

- `cursor` — optional, defaults to `0`. Pass back the `cursor` from the previous response to continue; `0` in a response means the scan reached the end.
- `limit` — optional, defaults to `100` (1–1000). A page-size hint, not a hard cap.

**Response `200`**
```json
{
  "items": [
    {
      "key": "9c1e6f0b2a...",
      "url": "https://example.com/",
      "formats": ["markdown"],
      "robotstxt": true,
      "stage_won": "stage1_curl_cffi",
      "job_id": "74f499106ffa413197d238a9057c3ce6",
      "size_bytes": 4821,
      "created_at": "2026-08-25T04:16:18.791624Z"
    }
  ],
  "cursor": 0
}
```

---

## 6. Get one cache entry

**GET** `{{base_url}}/cache/{{cache_key}}`

**Response `200`**
```json
{
  "meta": {
    "key": "9c1e6f0b2a...",
    "url": "https://example.com/",
    "formats": ["markdown"],
    "robotstxt": true,
    "stage_won": "stage1_curl_cffi",
    "job_id": "74f499106ffa413197d238a9057c3ce6",
    "size_bytes": 4821,
    "created_at": "2026-08-25T04:16:18.791624Z"
  },
  "result": { "markdown": "# Example Domain\n\n..." }
}
```

**Response `404 Not Found`** — unknown or expired key.

---

## 7. Delete one cache entry

**DELETE** `{{base_url}}/cache/{{cache_key}}`

**Response `204 No Content`** — removed.
**Response `404 Not Found`** — unknown or already expired.

---

## 8. Clear the whole cache

**DELETE** `{{base_url}}/cache`

Scoped to the cache's own key prefixes. Job records and the arq queue share the same Redis database and are left intact.

**Response `200`**
```json
{ "deleted": 42 }
```

---

## Typical Postman flow

1. Run **Create Job** → captures `job_id` into the environment.
2. Run **Get Job** repeatedly (or add a Postman "Runner" loop / a small `setTimeout` + retry test script) until `status` leaves `queued`/`running`.
3. Read `result` off the final response.
4. Re-run **Create Job** with the identical body → the response comes back immediately with `"cached": true` and `"status": "success"`.
5. Run **Get One Cache Entry** with the captured `cache_key`, then **Delete One Cache Entry**, then re-run **Create Job** → it queues a real fetch again.
