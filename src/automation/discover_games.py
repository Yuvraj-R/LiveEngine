from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from zoneinfo import ZoneInfo

from src.connectors.nba.scoreboard_client import NBAScoreboardClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
SERIES_TICKER = "KXNBAGAME"

# Centralized storage for jobs
PROJECT_ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = PROJECT_ROOT / "src" / "storage" / "jobs"

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("discover_games")


@dataclass
class Job:
    game_date: str        # YYYY-MM-DD
    game_id: str
    home_team: str
    away_team: str
    tipoff_utc: Optional[str]   # ISO string or None
    event_ticker: str
    market_tickers: List[str]


# ---------------------------------------------------------------------------
# Kalshi Helpers
# ---------------------------------------------------------------------------

def _fetch_kalshi_events() -> List[Dict[str, Any]]:
    """Fetch all open NBA events from Kalshi."""
    url = f"{KALSHI_BASE_URL}/events"
    params = {
        "series_ticker": SERIES_TICKER,
        "with_nested_markets": "true",
        "status": "open",
        "limit": 200,
    }

    log.info(f"Fetching Kalshi events from {url}")
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error(f"Failed to fetch Kalshi events: {e}")
        return []

    if isinstance(data, dict):
        events = data.get("events", []) or []
    elif isinstance(data, list):
        events = data
    else:
        events = []

    log.info(f"Found {len(events)} Kalshi events")
    return events


def _parse_nba_event_ticker(event_ticker: str) -> Optional[Tuple[date, str, str]]:
    """
    Parse 'KXNBAGAME-25NOV22LACCHA' -> (date(2025, 11, 22), 'LAC', 'CHA')
    """
    try:
        _, suffix = event_ticker.split("-", 1)
        if len(suffix) < 13:
            return None

        date_code = suffix[:7]  # "25NOV22"
        yy = int(date_code[:2])
        mon_str = date_code[2:5]
        day = int(date_code[5:7])

        month = datetime.strptime(mon_str, "%b").month
        year = 2000 + yy
        event_dt = date(year, month, day)

        away = suffix[7:10]
        home = suffix[10:13]
        return event_dt, away, home
    except Exception:
        return None


def _extract_winner_markets(event: Dict[str, Any]) -> List[str]:
    """Find the two 'Winner' moneyline markets in an event."""
    markets = event.get("markets") or []
    tickers = []
    for m in markets:
        # We only want binary winner markets (Moneyline)
        if m.get("market_type") == "binary" and "winner" in (m.get("title") or "").lower():
            if t := m.get("ticker"):
                tickers.append(t)
    return tickers


# ---------------------------------------------------------------------------
# Core Discovery Logic
# ---------------------------------------------------------------------------

def discover_jobs_for_date(target_date: date) -> List[Job]:
    log.info(f"Discovering jobs for {target_date}")

    # 1. Get NBA Schedule
    # We reuse your existing NBAScoreboardClient logic indirectly or just raw call
    # But for discovery, we need the FULL schedule, not just live updates.
    # We will use the raw scoreboardv2 logic similar to your old script to be safe.

    # Instantiate client just to get the helper logic if needed,
    # but here we'll effectively inline the schedule fetch to keep this script standalone-ish.
    client = NBAScoreboardClient()
    nba_snapshots = client.fetch_scoreboard_for_date(target_date)

    # 2. Get Kalshi Events
    kalshi_events = _fetch_kalshi_events()

    # Index Kalshi events by (home, away)
    kalshi_index = {}
    for e in kalshi_events:
        et = e.get("event_ticker") or e.get("ticker")
        if not et:
            continue

        parsed = _parse_nba_event_ticker(et)
        if not parsed:
            continue

        evt_date, away, home = parsed
        if evt_date == target_date:
            kalshi_index[(home, away)] = e

    jobs = []

    # 3. Match
    for gid, snap in nba_snapshots.items():
        key = (snap.home_team, snap.away_team)
        k_event = kalshi_index.get(key)

        if not k_event:
            log.warning(
                f"No Kalshi event for NBA game {snap.away_team} @ {snap.home_team}")
            continue

        market_tickers = _extract_winner_markets(k_event)
        if len(market_tickers) != 2:
            log.warning(
                f"Skipping {key}: Found {len(market_tickers)} markets, expected 2")
            continue

        # Parse tipoff from status if possible, else None (Worker will handle immediate start)
        # NBAScoreboardSnapshot doesn't store raw tipoff time, only status text.
        # We'll rely on the worker to sleep if the status says "7:00 PM ET".

        job = Job(
            game_date=target_date.isoformat(),
            game_id=gid,
            home_team=snap.home_team,
            away_team=snap.away_team,
            tipoff_utc=None,  # Todo: Parse if strictly needed, but Worker handles "pre-game" sleep
            event_ticker=k_event.get("event_ticker"),
            market_tickers=market_tickers
        )
        jobs.append(job)

    log.info(f"Discovered {len(jobs)} valid jobs.")
    return jobs


def _save_jobs(jobs: List[Job], target_date: date):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    filename = JOBS_DIR / f"jobs_{target_date.isoformat()}.json"

    with open(filename, "w") as f:
        json.dump([asdict(j) for j in jobs], f, indent=2)

    log.info(f"Saved jobs to {filename}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD", default=None)
    args = parser.parse_args()

    if args.date:
        d = date.fromisoformat(args.date)
    else:
        d = datetime.now(ZoneInfo("America/New_York")).date()

    jobs = discover_jobs_for_date(d)
    _save_jobs(jobs, d)
