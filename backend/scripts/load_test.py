"""Indicative load test for a local or staging deployment.

Drives complete voter flows (OTP -> credential -> prepare -> cast) in parallel
against a running API. This is NOT a substitute for independent performance
testing; SQLite and a single Uvicorn worker bound the result.

    python scripts/load_test.py --voters 12 --workers 6
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import smoke_test as st  # noqa: E402


def vote(election: dict, voter_id: str) -> float:
    started = time.perf_counter()
    credential = st.issue_credential(election, voter_id)
    prepared = st.prepare(election, credential, st.selections_for(election))
    st.call("POST", f"/voting/{prepared['prepared_id']}/cast", json=credential)
    return time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description="Run concurrent voter flows")
    parser.add_argument("--voters", type=int, default=12, help="number of voters (max 24 seeded)")
    parser.add_argument("--workers", type=int, default=6, help="parallel workers")
    args = parser.parse_args()

    election = st.public_election()
    # Seeded register: SJC/AL/<year>/<sequence>, two voters per year from 2004.
    voters = [
        f"SJC/AL/{2004 + (index - 1) // 2}/{index:03d}"
        for index in range(1, min(args.voters, 24) + 1)
    ]

    print(f"voters={len(voters)} workers={args.workers} election={election['reference']}")
    started = time.perf_counter()
    latencies: list[float] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(vote, election, voter): voter for voter in voters}
        for future in as_completed(futures):
            voter = futures[future]
            try:
                latencies.append(future.result())
            except Exception as exc:  # report, never mask a failed flow
                errors.append(f"{voter}: {type(exc).__name__}: {exc}")

    wall = time.perf_counter() - started
    if latencies:
        ordered = sorted(latencies)
        print(f"completed: {len(latencies)}/{len(voters)} in {wall:.2f}s "
              f"({len(latencies) / wall:.2f} ballots/s)")
        print(f"latency p50={statistics.median(ordered):.3f}s "
              f"p95={ordered[max(0, int(len(ordered) * 0.95) - 1)]:.3f}s "
              f"max={ordered[-1]:.3f}s")
    for error in errors:
        print(f"  FAILED {error}")
    print("note: local SQLite + single Uvicorn worker; not a capacity guarantee.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
