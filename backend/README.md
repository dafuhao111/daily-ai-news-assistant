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

## Migrations and run

```powershell
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The API rejects non-loopback Host headers and state-changing requests without a local Origin and JSON content type. It does not implement authentication or expose mail/model secrets.

Available endpoints in this phase:

- `GET` / `PUT` `/api/v1/profile`
- `GET` / `PUT` `/api/v1/preferences`
- `GET` `/api/v1/health`

Preferences cannot be enabled until an email is configured and its test status is successful. Mail testing is implemented in a later phase.

## Task tools

`app.tools.create_default_registry()` registers `list_dir`, `read_file`, `search_content`, `write_file`, and `bash`, validates inputs with Pydantic, and exposes OpenAI-compatible Function Schemas through `model_schemas()`. Each invocation receives its workspace root from the task runner; the model cannot choose that root.

File access is limited to `inputs/` and `history/` for reads/searches, and `drafts/` for writes. The task runner must provide a dedicated workspace with a current-user-only Windows ACL. Hidden items, links/reparse points, hard-linked files, denied extensions, oversized files, and paths outside the workspace are rejected or skipped. Handle-level protection against same-user path races remains to be verified on Windows. Tool responses are returned as stable JSON error codes and capped at 12 KiB when serialized for a model.

The `bash` tool is registered and validates a single `python -m json.tool <workspace-file>` command shape, but returns `sandbox_unavailable` without starting a process. Windows low-privilege isolation and process-tree resource controls have not been verified, so command execution remains disabled by design.

## Agent loop

`app.agent.AgentRunner` binds the registry's Function Schemas to a LangChain chat model and runs an explicit LangGraph decision loop. Each returned Tool Call is validated and dispatched by the registry; its result is sent back as a `ToolMessage` with the same call ID. Read-only batches execute serially. A batch that mixes a side-effecting tool (`write_file` or `bash`) with another call is rejected as `unsafe_parallel_batch`.

Set `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` in the untracked `.env` for an OpenAI-compatible endpoint that supports multi-turn Tool Calling. Use the provider's actual model ID. An ordinary text-only endpoint is not sufficient. The API key stays server-side and is never part of the task context or trace. Limits default to 45 seconds per model request, 8 tool rounds, 8 calls per model response, and 300 seconds per task. Provider token usage is recorded only when the response supplies it; no invoice cost is inferred.

## RSS sources

The RSS tools use a local JSON source catalog. No source is preselected because the product design leaves the actual feeds for confirmation. Copy `config/rss_sources.example.json` to `config/rss_sources.json`, then add only feeds you have chosen and checked. The live file is ignored by Git. Each entry contains `source_id`, `name`, `feed_url`, `allowed_hosts`, `category`, and `enabled`. `allowed_hosts` must include the configured feed host and any approved article hosts. Only enabled source IDs, names, and categories are shown to the model; feed URLs are never included in its prompt.

`fetch_rss` reads only those configured feeds, with a 2 MiB response cap, bounded redirects, timeouts, DNS/IP checks, and exact allowed-host checks. `search_news` searches only candidates loaded for the current task and does not use a third-party search service. `fetch_article` accepts only an article ID from that task and uses the source's allowed hosts. RSS and public article access normally need no account or paid search API; a feed that requires credentials is not supported by this configuration. DNS is checked before each request and redirect, but a same-host DNS rebinding race remains a Windows/network-layer limitation.

The `rss_source` and `news_item` tables persist configured sources, fetched material, article text, canonical URL hashes, and an inclusion marker. Article text is stored with a 24 KiB cap; `fetch_article` returns 2,500-character chunks on repeated model calls and reports when the source text was truncated. The repository returns previously fetched items again after a failed task until a later brief transaction marks them included. When the task runner passes a `NewsRepository` into `create_tool_context`, exact URL duplicates are suppressed across tasks. `mark_task_success` is designed to update inclusion markers and source cursors inside the same transaction that saves a successful brief; it must not be called for failed or partial runs.

Mock HTTP tests use `httpx.MockTransport` and do not access the network. To check a real configured feed, opt in explicitly:

```powershell
$env:RUN_LIVE_RSS_TESTS = "1"
uv run pytest -m live_rss tests/integration/test_live_rss.py
Remove-Item Env:RUN_LIVE_RSS_TESTS
```

Mock-driven loop tests run with the normal suite and make no network requests. A real endpoint path is available, but requires explicit opt-in because it can incur provider charges:

```powershell
$env:RUN_REAL_LLM_TESTS = "1"
uv run pytest -m real_llm tests/integration/test_real_llm.py
Remove-Item Env:RUN_REAL_LLM_TESTS
```

That test asks the configured model to call `list_dir` once, checks the real Tool Calling round trip, and then checks the final response. It is skipped unless the opt-in flag and non-placeholder endpoint, model ID, and API key are configured.

## Tests

```powershell
uv run pytest
```

Tests use an isolated SQLite database for repeatable API and migration coverage. A MySQL integration run requires a separately configured disposable test schema and is not implied by the SQLite results.
