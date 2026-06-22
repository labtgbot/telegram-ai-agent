"""Validate GitHub workflow supply-chain guardrails."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
DEPLOY_WORKFLOW = WORKFLOWS_DIR / "deploy.yml"
K8S_VALIDATION_STEP = "Validate Kubernetes manifests against schemas"

USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([^'\"\s#]+)")
FULL_SHA_REF_RE = re.compile(r"^[^@]+@[0-9a-fA-F]{40}$")
ACTION_REF_RE = re.compile(r"^(?P<action>[^@]+)@(?P<ref>[0-9a-fA-F]{40})$")


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def _external_action_ref(ref: str) -> bool:
    return not (ref.startswith("./") or ref.startswith("docker://"))


def _action_pin_errors() -> list[str]:
    errors: list[str] = []
    for workflow in _workflow_files():
        for line_number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = USES_RE.match(line)
            if match is None:
                continue

            ref = match.group(1)
            if _external_action_ref(ref) and FULL_SHA_REF_RE.match(ref) is None:
                rel_path = workflow.relative_to(REPO_ROOT)
                errors.append(f"{rel_path}:{line_number}: action ref is not SHA-pinned: {ref}")
    return errors


def _action_consistency_errors() -> list[str]:
    refs_by_action: dict[str, dict[str, list[str]]] = {}

    for workflow in _workflow_files():
        for line_number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = USES_RE.match(line)
            if match is None:
                continue

            ref = match.group(1)
            if not _external_action_ref(ref):
                continue

            action_ref = ACTION_REF_RE.match(ref)
            if action_ref is None:
                continue

            action = action_ref.group("action").lower()
            sha = action_ref.group("ref").lower()
            location = f"{workflow.relative_to(REPO_ROOT)}:{line_number}"
            refs_by_action.setdefault(action, {}).setdefault(sha, []).append(location)

    errors: list[str] = []
    for action, refs in refs_by_action.items():
        if len(refs) == 1:
            continue

        details = "; ".join(
            f"{sha[:12]} at {', '.join(locations)}"
            for sha, locations in sorted(refs.items())
        )
        errors.append(f"{action}: inconsistent pinned refs: {details}")

    return errors


def _step_block(path: Path, name: str) -> tuple[int, list[str]] | None:
    lines = path.read_text(encoding="utf-8").splitlines()
    start: int | None = None
    step_indent = 0

    for index, line in enumerate(lines):
        if line.strip() == f"- name: {name}":
            start = index
            step_indent = len(line) - len(line.lstrip())
            break

    if start is None:
        return None

    end = len(lines)
    next_step_re = re.compile(rf"^\s{{{step_indent}}}- name: ")
    for index in range(start + 1, len(lines)):
        if next_step_re.match(lines[index]):
            end = index
            break

    return start + 1, lines[start:end]


def _manifest_validation_errors() -> list[str]:
    errors: list[str] = []
    deploy_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    if "kubeval" in deploy_text:
        errors.append(
            f"{DEPLOY_WORKFLOW.relative_to(REPO_ROOT)}: "
            "kubeval is deprecated; use kubeconform"
        )

    block = _step_block(DEPLOY_WORKFLOW, K8S_VALIDATION_STEP)
    if block is None:
        errors.append(
            f"{DEPLOY_WORKFLOW.relative_to(REPO_ROOT)}: missing step {K8S_VALIDATION_STEP!r}"
        )
        return errors

    start_line, lines = block
    body = "\n".join(lines)
    if "kubeconform" not in body:
        errors.append(
            f"{DEPLOY_WORKFLOW.relative_to(REPO_ROOT)}:{start_line}: "
            "Kubernetes manifest validation does not run kubeconform"
        )
    if "continue-on-error" in body:
        errors.append(
            f"{DEPLOY_WORKFLOW.relative_to(REPO_ROOT)}:{start_line}: "
            "Kubernetes manifest validation must fail CI"
        )

    return errors


def main() -> int:
    errors = (
        _action_pin_errors()
        + _action_consistency_errors()
        + _manifest_validation_errors()
    )
    if errors:
        print("GitHub workflow validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("GitHub workflow validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
