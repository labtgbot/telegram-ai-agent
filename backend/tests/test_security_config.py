from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

BROAD_MARKDOWN_ALLOWLISTS = {
    r"(^|/).+\.md$",
    r"(^|/).*\.md$",
    r"(^|/)docs/.*\.md$",
}


def _load_gitleaks_config() -> dict[str, Any]:
    with (REPO_ROOT / ".gitleaks.toml").open("rb") as file:
        return tomllib.load(file)


def _global_allowlists(config: dict[str, Any]) -> list[dict[str, Any]]:
    allowlists = list(config.get("allowlists", []))
    legacy_allowlist = config.get("allowlist")
    if isinstance(legacy_allowlist, dict):
        allowlists.append(legacy_allowlist)
    return allowlists


def test_gitleaks_scans_markdown_by_default() -> None:
    config = _load_gitleaks_config()
    paths = [
        path
        for allowlist in _global_allowlists(config)
        for path in allowlist.get("paths", [])
    ]

    assert not BROAD_MARKDOWN_ALLOWLISTS.intersection(paths)


def test_gitleaks_change_me_allowlist_is_scoped_to_known_lines() -> None:
    config = _load_gitleaks_config()
    placeholder_allowlists = [
        allowlist
        for allowlist in _global_allowlists(config)
        if any(
            "change-me" in regex or "CHANGEME" in regex
            for regex in allowlist.get("regexes", [])
        )
    ]

    assert placeholder_allowlists
    for allowlist in placeholder_allowlists:
        assert allowlist.get("condition") == "AND"
        assert allowlist.get("regexTarget") == "line"
        assert allowlist.get("paths")
        assert not BROAD_MARKDOWN_ALLOWLISTS.intersection(allowlist.get("paths", []))


def test_npm_audit_blocks_high_runtime_advisories() -> None:
    security_workflow = (REPO_ROOT / ".github/workflows/security.yml").read_text(
        encoding="utf-8"
    )

    assert "--audit-level=critical" not in security_workflow
    assert "--audit-level=high" in security_workflow
