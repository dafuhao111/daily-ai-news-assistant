# Backend

Local single-user API foundation for the Daily AI News Assistant.

## Setup

Use Python 3.10 or newer. From this directory, install the pinned dependencies from `uv.lock`:

```powershell
python -m pip install uv==0.13.9
uv sync --locked --extra dev
Copy-Item .env.example .env
```

Before starting, create the `daily_ai_news` database with `utf8mb4` and a dedicated least-privilege MySQL account. Replace the placeholder `DATABASE_URL` in the untracked `.env`; do not use MySQL root or commit credentials.

The locked `pymysql[rsa]` dependency includes the cryptography support required for MySQL 8 `caching_sha2_password` authentication. Do not weaken the database account's authentication plugin to work around a missing dependency.

## Migrations and run

```powershell
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The API rejects non-loopback Host headers and state-changing requests without a local Origin and JSON content type. It does not implement authentication or expose mail/model secrets.

Available endpoints in this phase:

- `GET` / `PUT` `/api/v1/profile`
- `GET` / `PUT` `/api/v1/preferences`
- `POST` `/api/v1/runs` and `GET` `/api/v1/runs/{run_id}`
- `GET` `/api/v1/mail/status`, `POST` `/api/v1/mail/test`, and `POST` `/api/v1/mail/test/confirm`
- `POST` `/api/v1/briefs/{brief_id}/delivery/retry`
- `GET` `/api/v1/health`

Preferences cannot be enabled until an email is configured, an SMTP test message is accepted, and the user confirms receiving it. `POST /api/v1/mail/test` always sends to the saved profile address; the body cannot override the recipient. A successful SMTP response is shown as `pending` until the user checks their inbox and calls `/api/v1/mail/test/confirm`.

## Daily tasks and email delivery

When a database is configured and `SCHEDULER_ENABLED=true`, APScheduler loads each enabled user's saved local run time and IANA timezone. On startup it only catches up today's queued or interrupted run; it does not backfill previous days. MySQL advisory locking elects one scheduler process, and the database idempotency key `daily:<user_id>:<local-date>` prevents duplicate daily runs. Keep the API in a single Uvicorn worker as documented in the technical plan. Agent workspaces default to the current user's application-data directory; if `AGENT_WORKSPACE_DIR` is overridden, make sure the directory is private to that OS user.

Email uses the standard-library SMTP client and an existing mailbox provider. No provider or account is bundled or assumed to be available. Provider SMTP host, port, TLS mode, app-password requirements, quotas, and paid-plan requirements vary; confirm those details with the chosen provider. Configure these local environment variables:

- `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY` (`starttls`, `ssl`, or unauthenticated `none`), and `SMTP_FROM_EMAIL`
- `SMTP_USERNAME` and `SMTP_PASSWORD` together when the server requires authentication; authenticated `none` mode is rejected
- `SMTP_TIMEOUT_SECONDS`, `SMTP_MAX_ATTEMPTS`, and `SMTP_RETRY_BASE_SECONDS` for bounded timeouts and backoff

The `.env.example` contains only commented placeholders. A test send is never attempted automatically. The task run, redacted tool-call diagnostics, brief, selected-news markers, and mail-delivery row commit atomically. The delivery row snapshots the saved recipient after checking the current subscription and mail confirmation; the SMTP sender checks those values again before sending. SMTP acceptance is recorded as `submitted`, not delivered. The generated RFC Message-ID is not treated as a provider receipt. Explicit temporary rejections retry at most three times by default with exponential backoff. Permanent failures can be manually retried up to three times using the saved brief. An uncertain SMTP result is `unknown`, is not retried automatically, and the retry endpoint rejects it to avoid duplicate email. A process restart converts an in-flight `sending` attempt to `unknown`.

To trigger a run in development, first confirm the saved email test and enable preferences, then send the local API request:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/runs" `
  -Headers @{ Origin = "http://127.0.0.1:5173"; "Idempotency-Key" = "manual-check-1" } `
  -ContentType "application/json" -Body "{}"
```

The response contains a `run_id`; poll `/api/v1/runs/{run_id}` for status. Tests use fake SMTP and mocked RSS/model services and never send real email. No real SMTP account is configured or verified by this repository.

## Task tools

`app.tools.create_default_registry()` registers `list_dir`, `read_file`, `search_content`, `write_file`, and `bash`, validates inputs with Pydantic, and exposes OpenAI-compatible Function Schemas through `model_schemas()`. Each invocation receives its workspace root from the task runner; the model cannot choose that root.

File access is limited to `inputs/` and `history/` for reads/searches, and `drafts/` for writes. The task runner must provide a dedicated workspace with a current-user-only Windows ACL. Hidden items, links/reparse points, hard-linked files, denied extensions, oversized files, and paths outside the workspace are rejected or skipped. Handle-level protection against same-user path races remains to be verified on Windows. Tool responses are returned as stable JSON error codes and capped at 12 KiB when serialized for a model.

The `bash` tool is registered and validates a single `python -m json.tool <workspace-file>` command shape, but returns `sandbox_unavailable` without starting a process. Windows low-privilege isolation and process-tree resource controls have not been verified, so command execution remains disabled by design.

## Agent loop

`app.agent.AgentRunner` binds the registry's Function Schemas to a LangChain chat model and runs an explicit LangGraph decision loop. Each returned Tool Call is validated and dispatched by the registry; its result is sent back as a `ToolMessage` with the same call ID. Read-only batches execute serially. A batch that mixes a side-effecting tool (`write_file` or `bash`) with another call is rejected as `unsafe_parallel_batch`.

Set `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` in the untracked `.env` for an endpoint supporting multi-turn Tool Calling. `LLM_API_PROTOCOL` selects `chat_completions` (default) or `responses`; use the provider's documented base URL, since some gateways use a root endpoint rather than `/v1`. `LLM_MAX_OUTPUT_TOKENS` bounds each response (default 2,048); this is not a cumulative project budget. Both protocols use the same tool registry and Agent loop. Model requests set `store=false` and disable SDK retries. The API key stays server-side and is never part of the task context or trace. Limits default to 45 seconds per model request, 8 tool rounds, 8 calls per model response, and 300 seconds per task. Provider token usage is recorded only when the response supplies it; no invoice cost is inferred.

For this installation, the [Happy Code help center](https://cn.happycodeapi.com/help-center) documents a Responses endpoint: `https://happycodeapi.com` for regular access, with `https://cn.happycodeapi.com` as a backup. On 2026-11-22 the backup returned the configured `gpt-6.1-sol` model and passed a real `list_dir` Tool Call/result/final-answer round trip. The primary timed out and remains unverified. The current untracked local configuration uses the backup root URL, `LLM_API_PROTOCOL=responses`, and keeps scheduling disabled during setup. Never copy a Codex application's full client configuration into this project's `.env`; only the relevant endpoint, protocol, model, and local key are required.

## RSS sources

The RSS tools use a local JSON source catalog. The user confirmed OpenAI, Google DeepMind, and Microsoft Research as initial sources on 2026-11-21. Copy `config/rss_sources.example.json` to `config/rss_sources.json`; the live file is ignored by Git. The three public feeds were reachable and parsable during setup, which does not guarantee every linked article is readable or relevant. Each entry contains `source_id`, `name`, `feed_url`, `allowed_hosts`, `category`, and `enabled`. `allowed_hosts` must include the configured feed host and any approved article hosts. Only enabled source IDs, names, and categories are shown to the model; feed URLs are never included in its prompt.

`fetch_rss` reads only those configured feeds, with a 2 MiB response cap, bounded redirects, timeouts, DNS/IP checks, and exact allowed-host checks. `search_news` searches only candidates loaded for the current task and does not use a third-party search service. `fetch_article` accepts only an article ID from that task and uses the source's allowed hosts. RSS and public article access normally need no account or paid search API; a feed that requires credentials is not supported by this configuration. DNS is checked before each request and redirect, but a same-host DNS rebinding race remains a Windows/network-layer limitation.

The `rss_source` and `news_item` tables persist configured sources, fetched material, article text, canonical URL hashes, and an inclusion marker. Article text is stored with a 24 KiB cap; `fetch_article` returns 2,500-character chunks on repeated model calls and reports when the source text was truncated. The repository returns previously fetched items again after a failed task until a later brief transaction marks them included. When the task runner passes a `NewsRepository` into `create_tool_context`, exact URL duplicates are suppressed across tasks. `mark_task_success` is designed to update inclusion markers and source cursors inside the same transaction that saves a successful brief; it must not be called for failed or partial runs.

## Brief generation

`app.application.briefs.BriefGenerationService` accepts a frozen preference snapshot and loads only the task user's non-secret identity fields (display name and optional role) from the profile; it never reads the email field. Topics guide relevance, keywords affect priority, and excluded terms are enforced against the source title, source summary, and generated summary. The model chooses whether to fetch feeds, search candidates, read article text, repeat a tool, or finish; the service does not impose a news-tool sequence.

The model returns only article IDs, Chinese summaries, relevance reasons, and an empty-result reason. The service rejects malformed output, duplicate or undisclosed IDs, missing source evidence, disallowed source hosts, and excluded-keyword matches. It fills titles, source names, URLs, and publication evidence from the task's actual RSS candidates. Saved brief JSON separates the generated summary from a bounded source excerpt. The brief, task status, redacted tool-call diagnostics, usage data, and selected-news inclusion markers commit in one transaction. Empty briefs are saved with status `empty` only after the task has successful RSS evidence or recovered candidates; otherwise the task is recorded as failed. Tool-call diagnostics store argument summaries and short results, never raw tool arguments or prompts.

The generator is an application service for the scheduler and API integration stages; this stage does not expose a user-facing run endpoint. The Mock LLM tests cover distinct tool-choice traces for distinct preference snapshots. An optional real-model brief path uses a mocked RSS transport and calls only the configured LLM endpoint:

```powershell
$env:RUN_REAL_LLM_TESTS = "1"
uv run pytest -m real_llm tests/application/test_real_brief.py
Remove-Item Env:RUN_REAL_LLM_TESTS
```

This request may incur model charges. It does not contact a live RSS feed or send a push notification.

Mock HTTP tests use `httpx.MockTransport` and do not access the network. To check a real configured feed, opt in explicitly:

```powershell
$env:RUN_LIVE_RSS_TESTS = "1"
uv run pytest -m live_rss tests/integration/test_live_rss.py
Remove-Item Env:RUN_LIVE_RSS_TESTS
```

Mock-driven loop tests run with the normal suite and make no network requests. A real endpoint path is available, but requires explicit opt-in because it can incur provider charges:

```powershell
$env:RUN_REAL_LLM_TESTS = "1"
uv run pytest -m real_llm tests/integration/test_real_llm.py tests/application/test_real_brief.py
Remove-Item Env:RUN_REAL_LLM_TESTS
```

These tests check a real Tool Calling round trip and structured brief generation. They are skipped unless the opt-in flag and non-placeholder endpoint, model ID, and API key are configured.

## Tests

```powershell
uv run pytest
```

Tests use an isolated SQLite database for repeatable API and migration coverage. A MySQL integration run requires a separately configured disposable test schema and is not implied by the SQLite results.
