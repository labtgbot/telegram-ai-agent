#!/usr/bin/env python3
"""Create the GitHub issues for the #136 audit from the generated manifest.

Reads experiments/issues_manifest.json (produced by audit_issue_gen.py), creates
one issue per finding (labels = area labels + complexity + remediation stage),
then prints a markdown list of created issues for the epic + PR description.

Idempotency: skips a finding if an open issue with the same title already exists.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "experiments" / "issues_manifest.json").read_text())

STAGE_LABEL = {
    0: "stage-0-blocker",
    1: "stage-1-high",
    2: "stage-2-medium",
    3: "stage-3-low",
}


def run(args: list[str]) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()


def existing_titles() -> set[str]:
    out = run(["gh", "issue", "list", "--state", "all", "--limit", "300",
               "--json", "title"])
    return {i["title"] for i in json.loads(out)}


def main() -> None:
    have = existing_titles()
    created = []
    for m in MANIFEST:
        if m["title"] in have:
            print(f"SKIP (exists): {m['title']}")
            continue
        labels = list(m["labels"]) + [STAGE_LABEL[m["stage"]]]
        # ensure complexity label present (already in area labels list from gen)
        args = ["gh", "issue", "create", "--title", m["title"],
                "--body-file", str(ROOT / m["file"])]
        for lb in labels:
            args += ["--label", lb]
        url = run(args)
        num = url.rstrip("/").split("/")[-1]
        created.append((int(num), m))
        print(f"CREATED #{num}: {m['title']}")

    # Emit a markdown checklist grouped by stage for the epic / PR body.
    lines = []
    for stage in (0, 1, 2, 3):
        grp = [(n, m) for (n, m) in created if m["stage"] == stage]
        if not grp:
            continue
        lines.append(f"\n### Stage {stage}")
        for n, m in sorted(grp):
            lines.append(f"- [ ] #{n} — {m['title']}")
    (ROOT / "experiments" / "created_issues.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
