"""Parse Locust CSV stats and exit non-zero if the SLO is breached.

Run after ``locust --csv=<prefix> ...``::

    python load/check_results.py load/out/run_stats.csv \
        --max-p95-ms 500 --max-failure-ratio 0.01

The script reads the aggregated row (``Name == "Aggregated"``) and
compares it against the targets from issue #30: p95 < 500 ms with no
unexpected failures.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def _aggregated_row(path: Path) -> dict[str, str]:
    with path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("Name") == "Aggregated":
                return row
    raise SystemExit(f"no Aggregated row found in {path}")


def _percentile_field(row: dict[str, str], pct: int) -> float:
    # Locust 2.x writes columns like "95%" / "99%" for percentile latencies.
    key = f"{pct}%"
    try:
        return float(row[key])
    except KeyError as exc:
        raise SystemExit(f"CSV missing {key!r} column (got {sorted(row)})") from exc
    except ValueError as exc:
        raise SystemExit(f"could not parse {key!r}={row[key]!r}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Path to <prefix>_stats.csv")
    parser.add_argument(
        "--max-p95-ms",
        type=float,
        default=500.0,
        help="Fail if aggregated p95 latency (ms) exceeds this value.",
    )
    parser.add_argument(
        "--max-failure-ratio",
        type=float,
        default=0.0,
        help=(
            "Fail if (failures / requests) exceeds this ratio. "
            "Default 0.0 means any failure fails the check."
        ),
    )
    parser.add_argument(
        "--min-rps",
        type=float,
        default=0.0,
        help=(
            "Optional floor on observed RPS (Requests/s column). Useful in "
            "CI smoke runs to catch a totally idle locust."
        ),
    )
    args = parser.parse_args()

    if not args.csv_path.exists():
        print(f"::error::{args.csv_path} does not exist", file=sys.stderr)
        return 2

    row = _aggregated_row(args.csv_path)
    requests = int(row.get("Request Count", "0") or 0)
    failures = int(row.get("Failure Count", "0") or 0)
    rps = float(row.get("Requests/s", "0") or 0)
    p50 = _percentile_field(row, 50)
    p95 = _percentile_field(row, 95)
    p99 = _percentile_field(row, 99)

    ratio = failures / requests if requests else (1.0 if failures else 0.0)
    print(
        "summary: "
        f"requests={requests} failures={failures} "
        f"failure_ratio={ratio:.4f} rps={rps:.1f} "
        f"p50={p50:.0f}ms p95={p95:.0f}ms p99={p99:.0f}ms"
    )

    errors: list[str] = []
    if requests == 0:
        errors.append("zero requests recorded — locust may not have started load")
    if ratio > args.max_failure_ratio:
        errors.append(
            f"failure_ratio={ratio:.4f} > {args.max_failure_ratio:.4f}"
        )
    if p95 > args.max_p95_ms:
        errors.append(f"p95={p95:.0f}ms > {args.max_p95_ms:.0f}ms")
    if args.min_rps > 0 and rps < args.min_rps:
        errors.append(f"rps={rps:.1f} < {args.min_rps:.1f}")

    if errors:
        for err in errors:
            print(f"::error::{err}", file=sys.stderr)
        return 1
    print("OK — within SLO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
