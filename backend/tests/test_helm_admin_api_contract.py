"""Regression tests for the admin dashboard API URL Helm contract."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

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


def _admin_deployment(rendered: str) -> dict[str, Any]:
    documents = yaml.safe_load_all(rendered)
    for document in documents:
        if not isinstance(document, dict) or document.get("kind") != "Deployment":
            continue
        labels = document.get("metadata", {}).get("labels", {})
        if labels.get("app.kubernetes.io/component") == "admin":
            return document
    raise AssertionError("rendered chart did not include the admin Deployment")


def _admin_env(rendered: str) -> dict[str, str]:
    deployment = _admin_deployment(rendered)
    containers = deployment["spec"]["template"]["spec"]["containers"]
    env = containers[0]["env"]
    return {item["name"]: item["value"] for item in env if "value" in item}


def test_helm_renders_non_localhost_admin_api_urls_for_production() -> None:
    _require_helm()

    result = _run_helm_template("--namespace", "tgai-prod", "--set", "image.tag=0.0.0-ci")

    assert result.returncode == 0, result.stderr
    env = _admin_env(result.stdout)
    assert env["API_BASE_URL"] == "http://telegram-ai-agent-backend:8000/api/v1"
    assert env["NEXT_PUBLIC_API_BASE_URL"] == "https://bot.example.com/api/v1"
    assert "localhost" not in env["API_BASE_URL"]
    assert "localhost" not in env["NEXT_PUBLIC_API_BASE_URL"]


def test_helm_rejects_localhost_admin_api_urls_for_production() -> None:
    _require_helm()

    result = _run_helm_template(
        "--namespace",
        "tgai-prod",
        "--set",
        "image.tag=0.0.0-ci",
        "--set",
        "admin.apiBaseUrl=http://localhost:8000/api/v1",
        "--set",
        "admin.publicApiBaseUrl=https://bot.example.com/api/v1",
    )

    assert result.returncode != 0
    assert "admin.apiBaseUrl" in result.stderr


def test_helm_requires_public_admin_api_url_without_ingress() -> None:
    _require_helm()

    result = _run_helm_template(
        "--namespace",
        "tgai-prod",
        "--set",
        "image.tag=0.0.0-ci",
        "--set",
        "ingress.enabled=false",
    )

    assert result.returncode != 0
    assert "admin.publicApiBaseUrl" in result.stderr
