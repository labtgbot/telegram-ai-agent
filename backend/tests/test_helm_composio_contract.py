"""Regression tests for Helm Composio production-safety validation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART_DIR = REPO_ROOT / "deploy" / "helm" / "telegram-ai-agent"
VALUES_FILE = CHART_DIR / "values.yaml"
PRODUCTION_VALUES_FILE = CHART_DIR / "values-production.yaml"


def _require_helm() -> None:
    if shutil.which("helm") is None:
        pytest.skip("helm is not installed")


def _run_helm_template(*extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "helm",
            "template",
            "telegram-ai-agent",
            str(CHART_DIR),
            "-f",
            str(VALUES_FILE),
            "-f",
            str(PRODUCTION_VALUES_FILE),
            *extra_args,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_helm_rejects_mock_composio_mode_for_production() -> None:
    _require_helm()

    result = _run_helm_template("--set", "config.COMPOSIO_MODE=mock")

    assert result.returncode != 0
    assert "COMPOSIO_MODE" in result.stderr


def test_helm_secret_create_requires_composio_api_key_for_production() -> None:
    _require_helm()

    result = _run_helm_template("--set", "secret.create=true")

    assert result.returncode != 0
    assert "COMPOSIO_API_KEY" in result.stderr
