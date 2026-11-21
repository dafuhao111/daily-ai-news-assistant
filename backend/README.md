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

## Tests

```powershell
uv run pytest
```

Tests use an isolated SQLite database for repeatable API and migration coverage. A MySQL integration run requires a separately configured disposable test schema and is not implied by the SQLite results.
