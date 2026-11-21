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

## Tests

```powershell
uv run pytest
```

Tests use an isolated SQLite database for repeatable API and migration coverage. A MySQL integration run requires a separately configured disposable test schema and is not implied by the SQLite results.
