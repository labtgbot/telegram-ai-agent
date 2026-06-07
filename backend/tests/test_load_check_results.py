from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_RESULTS = REPO_ROOT / "load" / "check_results.py"


def _write_stats(path: Path, *, p95_ms: int) -> None:
    fieldnames = [
        "Type",
        "Name",
        "Request Count",
        "Failure Count",
        "Requests/s",
        "50%",
        "95%",
        "99%",
    ]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "Type": "",
                "Name": "Aggregated",
                "Request Count": "1883",
                "Failure Count": "0",
                "Requests/s": "99.0",
                "50%": "140",
                "95%": str(p95_ms),
                "99%": "870",
            }
        )


def _run_check(stats_path: Path, max_p95_ms: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CHECK_RESULTS),
            str(stats_path),
            "--max-p95-ms",
            str(max_p95_ms),
            "--max-failure-ratio",
            "0.0",
            "--min-rps",
            "10",
        ],
        capture_output=True,
        check=False,
        text=True,
    )


def test_ci_smoke_budget_accepts_observed_runner_latency(tmp_path: Path) -> None:
    stats_path = tmp_path / "smoke_stats.csv"
    _write_stats(stats_path, p95_ms=550)

    result = _run_check(stats_path, max_p95_ms=600)

    assert result.returncode == 0
    assert "summary: requests=1883" in result.stdout
    assert "OK" in result.stdout


def test_full_slo_rejects_observed_runner_latency(tmp_path: Path) -> None:
    stats_path = tmp_path / "smoke_stats.csv"
    _write_stats(stats_path, p95_ms=550)

    result = _run_check(stats_path, max_p95_ms=500)

    assert result.returncode == 1
    assert "p95=550ms > 500ms" in result.stderr
