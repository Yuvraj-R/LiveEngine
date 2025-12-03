from __future__ import annotations
from src.automation.discover_games import discover_jobs_for_date, _save_jobs

import argparse
import json
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Fix path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


JOBS_DIR = PROJECT_ROOT / "src" / "storage" / "jobs"


def run_daily_cycle(target_date: date, dry_run: bool):
    print(f"--- [Manager] Starting cycle for {target_date} ---")

    # 1. Discover
    jobs = discover_jobs_for_date(target_date)
    _save_jobs(jobs, target_date)

    if not jobs:
        print("No jobs found. Exiting.")
        return

    # 2. Spawn Workers
    processes = []

    for job in jobs:
        print(f"--- Spawning Worker for {job.away_team} @ {job.home_team} ---")

        # Prepare arguments
        # market_tickers is a list, join it
        markets_str = ",".join(job.market_tickers)

        cmd = [
            sys.executable, "-m", "src.automation.game_worker",
            "--event-ticker", job.event_ticker,
            "--game-id", job.game_id,
            "--home", job.home_team,
            "--away", job.away_team,
            "--date", job.game_date,
            "--markets", markets_str
        ]

        if dry_run:
            cmd.append("--dry-run")

        # Spawn independent process
        # We redirect stdout/stderr to a log file per game if desired,
        # but for now let's let them inherit to see output in systemd logs.
        p = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))
        processes.append((job.event_ticker, p))

        # Stagger startups slightly
        time.sleep(1)

    print(f"--- All {len(processes)} workers spawned. Monitoring... ---")

    # 3. Monitor
    # Simple wait loop. In a more advanced version, we could restart crashed workers.
    active = processes[:]
    while active:
        for item in active[:]:
            ticker, p = item
            ret = p.poll()
            if ret is not None:
                print(f"[Manager] Worker {ticker} finished with code {ret}")
                active.remove(item)
        time.sleep(5)

    print("--- [Manager] All workers finished. Cycle complete. ---")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD", default=None)
    parser.add_argument("--live", action="store_true",
                        help="If set, runs REAL MONEY trades (dry_run=False)")
    args = parser.parse_args()

    if args.date:
        d = date.fromisoformat(args.date)
    else:
        d = datetime.now(ZoneInfo("America/New_York")).date()

    # Logic inversion: The worker script flag is --dry-run.
    # If user passes --live here, we do NOT pass --dry-run to worker.
    # If user does NOT pass --live, we pass --dry-run to worker.
    is_dry_run = not args.live

    if not is_dry_run:
        print("!!! WARNING: RUNNING IN LIVE TRADING MODE !!!")
        time.sleep(3)

    run_daily_cycle(d, is_dry_run)
