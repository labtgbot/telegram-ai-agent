"""Regression tests for the production Docker Compose hardening contract."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker" / "compose.prod.yml"
CADDY_FILE = REPO_ROOT / "docker" / "Caddyfile.prod"

COMPOSE_ENV_KEYS = {
    "ACME_EMAIL",
    "ADMIN_DOMAIN",
    "ADMIN_IMAGE",
    "BACKEND_IMAGE",
    "CADDY_CONFIG_DIR",
    "CADDY_DATA_DIR",
    "DOMAIN",
    "MINI_APP_IMAGE",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
}

VALID_ENV = {
    "DOMAIN": "bot.example.com",
    "ADMIN_DOMAIN": "admin.example.com",
    "ACME_EMAIL": "ops@example.com",
    "CADDY_DATA_DIR": "/srv/tgai/caddy/data",
    "CADDY_CONFIG_DIR": "/srv/tgai/caddy/config",
    "POSTGRES_PASSWORD": "postgres-prod-password",
    "REDIS_PASSWORD": "redis-prod-password",
    "BACKEND_IMAGE": "ghcr.io/labtgbot/telegram-ai-agent/backend:0.1.0",
    "MINI_APP_IMAGE": "ghcr.io/labtgbot/telegram-ai-agent/mini-app:0.1.0",
    "ADMIN_IMAGE": "ghcr.io/labtgbot/telegram-ai-agent/admin:0.1.0",
}


def _require_docker_compose() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    result = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"docker compose is not available: {result.stderr}")


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in COMPOSE_ENV_KEYS:
        env.pop(key, None)
    env["COMPOSE_PROJECT_NAME"] = "tgai-compose-prod-test"
    return env


def _run_compose_config(
    tmp_path: Path, env_values: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    project = tmp_path / "project"
    docker_dir = project / "docker"
    docker_dir.mkdir(parents=True)
    shutil.copy2(COMPOSE_FILE, docker_dir / "compose.prod.yml")
    shutil.copy2(CADDY_FILE, docker_dir / "Caddyfile.prod")

    env_file = project / ".env.prod"
    env_file.write_text(
        "".join(f"{key}={value}\n" for key, value in env_values.items()),
        encoding="utf-8",
    )

    return subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(docker_dir / "compose.prod.yml"),
            "--env-file",
            str(env_file),
            "config",
            "--format",
            "json",
        ],
        cwd=project,
        env=_clean_env(),
        capture_output=True,
        text=True,
    )


def test_prod_compose_requires_explicit_release_images(tmp_path: Path) -> None:
    _require_docker_compose()
    env_without_images = {
        key: value
        for key, value in VALID_ENV.items()
        if key not in {"BACKEND_IMAGE", "MINI_APP_IMAGE", "ADMIN_IMAGE"}
    }

    result = _run_compose_config(tmp_path, env_without_images)

    assert result.returncode != 0
    assert any(
        image_var in result.stderr
        for image_var in ("ADMIN_IMAGE", "BACKEND_IMAGE", "MINI_APP_IMAGE")
    )


def test_prod_compose_hardening_contract(tmp_path: Path) -> None:
    _require_docker_compose()

    result = _run_compose_config(tmp_path, VALID_ENV)

    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    services = config["services"]

    expected_health_commands = {
        "admin": "node",
        "backend": "python",
        "caddy": "caddy",
        "mini-app": "nginx",
        "postgres": "pg_isready",
        "redis": "redis-cli",
    }

    assert set(expected_health_commands).issubset(services)
    for name, expected_command in expected_health_commands.items():
        service = services[name]
        user = service.get("user", "")
        assert user
        assert not user.startswith("0:")
        assert user != "root"
        assert service["read_only"] is True
        assert "ALL" in service.get("cap_drop", [])
        assert "no-new-privileges:true" in service.get("security_opt", [])

        limits = service.get("deploy", {}).get("resources", {}).get("limits", {})
        assert limits.get("cpus")
        assert limits.get("memory")

        healthcheck = service["healthcheck"]
        healthcheck_command = " ".join(str(part) for part in healthcheck["test"])
        assert expected_command in healthcheck_command
        assert "wget" not in healthcheck_command.lower()
        assert healthcheck.get("start_period")

        image = service["image"]
        assert not image.endswith(":latest")
        assert ":latest@" not in image

    redis_command = " ".join(services["redis"]["command"])
    assert "--requirepass redis-prod-password" in redis_command
    assert services["redis"]["environment"]["REDIS_PASSWORD"] == "redis-prod-password"
    assert services["backend"]["environment"]["REDIS_URL"] == (
        "redis://:redis-prod-password@redis:6379/0"
    )

    caddy = services["caddy"]
    assert caddy["entrypoint"] == ["/bin/sh", "-c"]
    assert "/tmp/caddy run" in "\n".join(caddy["command"])
    assert "/tmp/caddy" in " ".join(caddy["healthcheck"]["test"])
    assert any(mount.startswith("/tmp:") and "exec" in mount for mount in caddy["tmpfs"])
