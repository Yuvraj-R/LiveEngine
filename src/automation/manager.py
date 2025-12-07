# src/automation/manager.py
from __future__ import annotations
from src.automation.nfl.discover_games import _save_jobs as save_nfl_jobs
from src.automation.nfl.discover_games import discover_jobs_for_date as discover_nfl
from src.automation.discover_games import _save_jobs as save_nba_jobs
from src.automation.discover_games import discover_jobs_for_date as discover_nba

import argparse
import subprocess
import sys
import time
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Fix path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# NBA Imports

# NFL Imports

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][Manager][%(message)s]",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("manager")


def spawn_worker(sport: str, job: Any, dry_run: bool) -> subprocess.Popen:
    """
    Spawns a background worker process for a specific job.
    """
    markets_str = ",".join(job.market_tickers)

    # Determine which worker script to run
    if sport == "nba":
        module_path = "src.automation.game_worker"
    elif sport == "nfl":
        module_path = "src.automation.nfl.game_worker"
    else:
        raise ValueError(f"Unknown sport: {sport}")

    cmd = [
        sys.executable, "-m", module_path,
        "--event-ticker", job.event_ticker,
        "--game-id", job.game_id,
        "--home", job.home_team,
        "--away", job.away_team,
        "--date", job.game_date,
        "--markets", markets_str
    ]

    # Note: Workers read config.json for mode, but we keep the structure clean.

    # Redirect stdout/stderr to systemd journal (inherit)
    return subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))


def run_daily_cycle(target_date: date, dry_run: bool):
    log.info(f"--- Starting Daily Cycle for {target_date} ---")

    all_processes = []

    # -----------------------------
    # 1. NBA Cycle
    # -----------------------------
    try:
        log.info("Running NBA Discovery...")
        nba_jobs = discover_nba(target_date)
        save_nba_jobs(nba_jobs, target_date)

        if nba_jobs:
            log.info(f"Spawning {len(nba_jobs)} NBA workers...")
            for job in nba_jobs:
                p = spawn_worker("nba", job, dry_run)
                all_processes.append(("NBA", job.event_ticker, p))
                time.sleep(0.5)  # Stagger start
        else:
            log.info("No NBA games found.")

    except Exception as e:
        log.error(f"NBA Cycle Failed: {e}", exc_info=True)

    # -----------------------------
    # 2. NFL Cycle
    # -----------------------------
    try:
        log.info("Running NFL Discovery...")
        nfl_jobs = discover_nfl(target_date)
        save_nfl_jobs(nfl_jobs, target_date)

        if nfl_jobs:
            log.info(f"Spawning {len(nfl_jobs)} NFL workers...")
            for job in nfl_jobs:
                p = spawn_worker("nfl", job, dry_run)
                all_processes.append(("NFL", job.event_ticker, p))
                time.sleep(0.5)
        else:
            log.info("No NFL games found.")

    except Exception as e:
        log.error(f"NFL Cycle Failed: {e}", exc_info=True)

    # -----------------------------
    # 3. Monitor All
    # -----------------------------
    if not all_processes:
        log.info("No workers spawned. Exiting.")
        return

    log.info(f"Monitoring {len(all_processes)} active workers...")

    active = all_processes[:]
    while active:
        for item in active[:]:
            sport, ticker, p = item
            ret = p.poll()
            if ret is not None:
                log.info(
                    f"[{sport}] Worker {ticker} finished (Exit Code: {ret})")
                active.remove(item)
        time.sleep(5)

    log.info("--- All workers finished. Cycle Complete. ---")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD", default=None)
    # We keep the --live arg for manual override/testing if needed
    parser.add_argument("--live", action="store_true",
                        help="Force live mode (overrides config)")
    args = parser.parse_args()

    if args.date:
        d = date.fromisoformat(args.date)
    else:
        d = datetime.now(ZoneInfo("America/New_York")).date()

    # Note: The workers read 'live_config.json' directly to determine Dry/Live mode.
    # We pass this bool just for internal logic if needed later.
    is_dry_run = not args.live

    run_daily_cycle(d, is_dry_run)
