"""Regression tests for backend runtime dependency constraints."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_runtime_dependencies_do_not_pin_starlette_below_security_fix() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    dependencies = data["project"]["dependencies"]

    assert "prometheus-fastapi-instrumentator>=7.0,<8" not in dependencies
