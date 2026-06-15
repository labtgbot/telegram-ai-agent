#!/usr/bin/env python3
"""Validate rendered background worker manifests.

The chart intentionally runs existing ``python -m app.workers.*`` entrypoints
instead of a Celery app. This check fails CI when a production render drops a
required worker or points a command at a missing module.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

EXPECTED_DEPLOYMENTS = {
    "broadcast-worker": ["python", "-m", "app.workers.broadcast", "--loop"],
    "video-polling-worker": [
        "python",
        "-m",
        "app.workers.video_polling",
        "--loop",
        "--interval-s",
        "10",
    ],
}

EXPECTED_CRONJOBS = {
    "account-deletion-worker": ["python", "-m", "app.workers.account_deletion"],
    "admin-refresh-sessions-worker": ["python", "-m", "app.workers.admin_refresh_sessions"],
    "daily-analytics-worker": ["python", "-m", "app.workers.daily_analytics"],
    "subscriptions-worker": ["python", "-m", "app.workers.subscriptions"],
    "token-usage-partitions": ["python", "-m", "app.workers.token_usage_partitions"],
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rendered",
        action="append",
        required=True,
        type=Path,
        help="Rendered Helm YAML file. Can be passed more than once.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root used to verify worker module files.",
    )
    return parser.parse_args()


def _load_documents(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [doc for doc in yaml.safe_load_all(fh) if isinstance(doc, dict)]


def _component(doc: dict[str, Any]) -> str:
    return str(
        doc.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component", "")
    )


def _deployment_command(doc: dict[str, Any]) -> list[str]:
    containers = doc["spec"]["template"]["spec"]["containers"]
    return list(containers[0].get("command", []))


def _cronjob_command(doc: dict[str, Any]) -> list[str]:
    containers = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
    return list(containers[0].get("command", []))


def _module_file(repo_root: Path, module: str) -> Path:
    return repo_root / "backend" / Path(*module.split(".")).with_suffix(".py")


def _assert_command(
    repo_root: Path, component: str, command: list[str], expected: list[str]
) -> None:
    if command[: len(expected)] != expected:
        raise AssertionError(
            f"{component}: expected command prefix {expected!r}, got {command!r}"
        )
    if any("celery" in part.lower() for part in command):
        raise AssertionError(
            f"{component}: Celery command is not part of the runtime contract"
        )
    module = command[2]
    if not _module_file(repo_root, module).is_file():
        raise AssertionError(
            f"{component}: module {module!r} has no backend source file"
        )


def _validate_render(rendered: Path, repo_root: Path) -> None:
    docs = _load_documents(rendered)
    deployments = {
        _component(doc): doc
        for doc in docs
        if doc.get("kind") == "Deployment" and _component(doc)
    }
    cronjobs = {
        _component(doc): doc
        for doc in docs
        if doc.get("kind") == "CronJob" and _component(doc)
    }

    missing_deployments = sorted(set(EXPECTED_DEPLOYMENTS) - set(deployments))
    if missing_deployments:
        raise AssertionError(
            f"{rendered}: missing worker Deployments {missing_deployments}"
        )

    missing_cronjobs = sorted(set(EXPECTED_CRONJOBS) - set(cronjobs))
    if missing_cronjobs:
        raise AssertionError(f"{rendered}: missing worker CronJobs {missing_cronjobs}")

    for component, expected in EXPECTED_DEPLOYMENTS.items():
        _assert_command(
            repo_root, component, _deployment_command(deployments[component]), expected
        )

    for component, expected in EXPECTED_CRONJOBS.items():
        doc = cronjobs[component]
        if not doc.get("spec", {}).get("schedule"):
            raise AssertionError(f"{component}: schedule is empty")
        _assert_command(repo_root, component, _cronjob_command(doc), expected)


def main() -> int:
    args = _parse_args()
    repo_root = args.repo_root.resolve()
    for rendered in args.rendered:
        _validate_render(rendered.resolve(), repo_root)
    print("worker contract ok:", ", ".join(str(path) for path in args.rendered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
