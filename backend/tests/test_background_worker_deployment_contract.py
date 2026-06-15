"""Deployment contract tests for production background workers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
CHART_DIR = REPO_ROOT / "deploy" / "helm" / "telegram-ai-agent"
VALUES_FILE = CHART_DIR / "values.yaml"
PRODUCTION_VALUES_FILE = CHART_DIR / "values-production.yaml"
STAGING_VALUES_FILE = CHART_DIR / "values-staging.yaml"

EXPECTED_DEPLOYMENT_WORKERS = {
    "broadcast": "app.workers.broadcast",
    "video-polling": "app.workers.video_polling",
}

EXPECTED_CRON_WORKERS = {
    "account-deletion": "app.workers.account_deletion",
    "admin-refresh-sessions": "app.workers.admin_refresh_sessions",
    "daily-analytics": "app.workers.daily_analytics",
    "subscriptions": "app.workers.subscriptions",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _module_file(module: str) -> Path:
    return BACKEND_ROOT / Path(*module.split(".")).with_suffix(".py")


def _assert_python_module_command(command: list[str], module: str) -> None:
    assert command[:3] == ["python", "-m", module]
    assert "celery" not in " ".join(command).lower()
    assert _module_file(module).is_file()


def test_default_helm_values_define_all_background_worker_entrypoints() -> None:
    values = _load_yaml(VALUES_FILE)

    workers = values.get("backgroundWorkers")
    assert workers is not None
    assert workers["enabled"] is True

    deployments = workers.get("deployments", {})
    assert set(EXPECTED_DEPLOYMENT_WORKERS).issubset(deployments)
    for name, module in EXPECTED_DEPLOYMENT_WORKERS.items():
        worker = deployments[name]
        assert worker["enabled"] is True
        _assert_python_module_command(worker["command"], module)
        assert "--loop" in worker["command"]

    cron_jobs = workers.get("cronJobs", {})
    assert set(EXPECTED_CRON_WORKERS).issubset(cron_jobs)
    for name, module in EXPECTED_CRON_WORKERS.items():
        worker = cron_jobs[name]
        assert worker["enabled"] is True
        assert worker["schedule"]
        _assert_python_module_command(worker["command"], module)


def test_production_and_staging_overlays_keep_background_workers_enabled() -> None:
    for values_file in (PRODUCTION_VALUES_FILE, STAGING_VALUES_FILE):
        values = _load_yaml(values_file)
        assert "worker" not in values
        workers = values.get("backgroundWorkers")
        assert workers is not None
        assert workers["enabled"] is True


def test_chart_no_longer_references_unshipped_celery_worker() -> None:
    chart_sources = list(CHART_DIR.rglob("*.yaml")) + list(CHART_DIR.rglob("*.tpl"))
    stale_references: list[str] = []
    for path in chart_sources:
        text = path.read_text(encoding="utf-8").lower()
        if "app.workers.celery_app" in text or "celery" in text:
            stale_references.append(str(path.relative_to(REPO_ROOT)))

    assert stale_references == []
