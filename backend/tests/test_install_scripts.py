"""Run the actual PowerShell entry points in a disposable checkout with stub CLIs.

No dependencies are installed, no real DB is migrated and no mail/model is contacted.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHELLS = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]


@pytest.fixture(
    params=SHELLS or [None], ids=lambda path: Path(path).stem if path else "no-powershell"
)
def shell(request):
    if request.param is None:
        pytest.skip("PowerShell is required to exercise the Windows install scripts")
    return request.param


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout with spaces 中文"
    (root / "scripts").mkdir(parents=True)
    (root / "backend/config").mkdir(parents=True)
    (root / "frontend/dist").mkdir(parents=True)
    for name in ("setup.ps1", "start.ps1"):
        shutil.copy2(ROOT / "scripts" / name, root / "scripts" / name)
    shutil.copy2(ROOT / "backend/.env.example", root / "backend/.env.example")
    shutil.copy2(
        ROOT / "backend/config/rss_sources.example.json",
        root / "backend/config/rss_sources.example.json",
    )
    (root / "frontend/dist/index.html").write_text("<html></html>", encoding="utf-8")
    return root


def invoke(shell, checkout, tmp_path, script, *, prepare=False, fail_command="", node="v24.18.0"):
    log = tmp_path / "calls.jsonl"
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        """
param([string]$Script, [switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
function Record-Call {
    param([string]$Name, [string[]]$Values)
    @{ command=$Name; arguments=@($Values); cwd=(Get-Location).Path } |
        ConvertTo-Json -Compress | Add-Content -LiteralPath $env:INSTALL_TEST_LOG -Encoding UTF8
    $global:LASTEXITCODE = 0
    if ($env:INSTALL_TEST_FAIL -eq ($Name + ':' + ($Values -join ' '))) {
        $global:LASTEXITCODE = 7
    }
}
function uv { Record-Call -Name 'uv' -Values $args }
function npm.cmd { Record-Call -Name 'npm' -Values $args }
function node { Record-Call -Name 'node' -Values $args; $env:INSTALL_TEST_NODE }
try {
    if ($PrepareOnly) { & $Script -PrepareOnly } else { & $Script }
} catch {
    Write-Output $_.Exception.Message
    exit 1
}
""",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "INSTALL_TEST_LOG": str(log),
        "INSTALL_TEST_FAIL": fail_command,
        "INSTALL_TEST_NODE": node,
    }
    args = [
        shell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(harness),
        "-Script",
        str(checkout / "scripts" / script),
    ]
    if prepare:
        args.append("-PrepareOnly")
    result = subprocess.run(
        args, cwd=tmp_path, env=env, capture_output=True, timeout=30, check=False
    )
    calls = (
        [
            json.loads(line.lstrip("\ufeff"))
            for line in log.read_text(encoding="utf-8-sig").splitlines()
        ]
        if log.exists()
        else []
    )
    return result, calls


def test_first_setup_only_creates_safe_examples(shell, checkout, tmp_path):
    result, calls = invoke(shell, checkout, tmp_path, "setup.ps1")
    assert result.returncode == 0, result.stdout
    assert calls == []
    assert (checkout / "backend/.env").read_bytes() == (
        checkout / "backend/.env.example"
    ).read_bytes()
    assert "SCHEDULER_ENABLED=false" in (checkout / "backend/.env").read_text()
    assert (checkout / "backend/config/rss_sources.json").is_file()


def test_prepare_preserves_existing_configs(shell, checkout, tmp_path):
    env = checkout / "backend/.env"
    rss = checkout / "backend/config/rss_sources.json"
    env.write_bytes(b"EXISTING_LOCAL_CONFIG=keep\r\n")
    rss.write_bytes(b"[]\n")
    result, calls = invoke(shell, checkout, tmp_path, "setup.ps1", prepare=True)
    assert result.returncode == 0
    assert calls == []
    assert env.read_bytes() == b"EXISTING_LOCAL_CONFIG=keep\r\n"
    assert rss.read_bytes() == b"[]\n"


def test_setup_runs_locked_build_and_migrations_from_correct_directories(shell, checkout, tmp_path):
    (checkout / "backend/.env").write_text("LOCAL=keep")
    result, calls = invoke(shell, checkout, tmp_path, "setup.ps1")
    assert result.returncode == 0, result.stdout
    assert [(c["command"], c["arguments"]) for c in calls] == [
        ("node", ["--version"]),
        ("npm", ["ci"]),
        ("npm", ["run", "build"]),
        ("uv", ["sync", "--locked"]),
        ("uv", ["run", "--locked", "python", "-m", "alembic", "upgrade", "head"]),
    ]
    assert all(Path(c["cwd"]) == checkout / "frontend" for c in calls[1:3])
    assert all(Path(c["cwd"]) == checkout / "backend" for c in calls[3:])
    assert (checkout / "backend/.env").read_text() == "LOCAL=keep"


def test_setup_stops_before_migration_on_build_failure(shell, checkout, tmp_path):
    (checkout / "backend/.env").write_text("LOCAL=keep")
    result, calls = invoke(shell, checkout, tmp_path, "setup.ps1", fail_command="npm:run build")
    assert result.returncode != 0
    assert not any(c["command"] == "uv" for c in calls)


def test_setup_stops_before_migration_on_dependency_failure(shell, checkout, tmp_path):
    (checkout / "backend/.env").write_text("LOCAL=keep")
    result, calls = invoke(shell, checkout, tmp_path, "setup.ps1", fail_command="uv:sync --locked")
    assert result.returncode != 0
    assert calls[-1]["arguments"] == ["sync", "--locked"]
    assert not any("alembic" in c["arguments"] for c in calls)


def test_setup_rejects_old_node_before_installing(shell, checkout, tmp_path):
    (checkout / "backend/.env").write_text("LOCAL=keep")
    result, calls = invoke(shell, checkout, tmp_path, "setup.ps1", node="v20.19.0")
    assert result.returncode != 0
    assert [c["command"] for c in calls] == ["node"]


def test_start_from_other_directory_uses_project_python_and_one_local_worker(
    shell, checkout, tmp_path
):
    (checkout / "backend/.env").write_text("LOCAL=keep")
    result, calls = invoke(shell, checkout, tmp_path, "start.ps1")
    assert result.returncode == 0, result.stdout
    assert len(calls) == 1
    assert calls[0] == {
        "command": "uv",
        "arguments": [
            "run",
            "--locked",
            "python",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--workers",
            "1",
        ],
        "cwd": str(checkout / "backend"),
    }


@pytest.mark.parametrize("missing", ["backend/.env", "frontend/dist/index.html"])
def test_start_rejects_incomplete_install_without_launching(shell, checkout, tmp_path, missing):
    (checkout / "backend/.env").write_text("LOCAL=keep")
    (checkout / missing).unlink()
    result, calls = invoke(shell, checkout, tmp_path, "start.ps1")
    assert result.returncode != 0
    assert calls == []


def test_start_reports_server_failure(shell, checkout, tmp_path):
    (checkout / "backend/.env").write_text("LOCAL=keep")
    command = (
        "uv:run --locked python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1"
    )
    result, calls = invoke(shell, checkout, tmp_path, "start.ps1", fail_command=command)
    assert result.returncode != 0
    assert len(calls) == 1
