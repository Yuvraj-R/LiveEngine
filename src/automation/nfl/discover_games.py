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

from src.connectors.nfl.scoreboard_client import NFLScoreboardClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
SERIES_TICKER = "KXNFLGAME"

# Storage for NFL jobs
PROJECT_ROOT = Path(__file__).resolve().parents[3]
JOBS_DIR = PROJECT_ROOT / "src" / "storage" / "jobs" / "nfl"

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("nfl_discover")


@dataclass
class NFLJob:
    game_date: str        # YYYY-MM-DD
    game_id: str
    home_team: str
    away_team: str
    tipoff_utc: Optional[str]
    event_ticker: str
    market_tickers: List[str]


# ---------------------------------------------------------------------------
# Kalshi Helpers
# ---------------------------------------------------------------------------

def _fetch_kalshi_events() -> List[Dict[str, Any]]:
    url = f"{KALSHI_BASE_URL}/events"
    params = {
        "series_ticker": SERIES_TICKER,
        "with_nested_markets": "true",
        "status": "open",
        "limit": 200,
    }

    log.info(f"Fetching Kalshi NFL events...")
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

    return events


def _parse_kalshi_ticker(event_ticker: str) -> Optional[Tuple[str, str]]:
    """
    Parse 'KXNFLGAME-25DEC07TENCLE' -> ('TEN', 'CLE')
    Returns (Away, Home)
    """
    try:
        _, suffix = event_ticker.split("-", 1)
        # Suffix: 25DEC07TENCLE
        # Date is 7 chars: 25DEC07
        # Teams are the rest: TENCLE
        if len(suffix) < 13:
            return None

        team_str = suffix[7:]  # TENCLE
        # Assume 3-letter codes for NFL
        if len(team_str) == 6:
            away = team_str[:3]
            home = team_str[3:]
            return away, home
        # Handle cases like NYG (3) vs NO (2)? Kalshi usually standardizes to 2 or 3.
        # Let's rely on exact suffix matching in the main logic instead.
        return None
    except:
        return None


def _extract_winner_markets(event: Dict[str, Any]) -> List[str]:
    markets = event.get("markets") or []
    tickers = []
    for m in markets:
        # Binary Winner markets
        if m.get("market_type") == "binary" and "winner" in (m.get("title") or "").lower():
            if t := m.get("ticker"):
                tickers.append(t)
    return tickers

# ---------------------------------------------------------------------------
# Core Discovery
# ---------------------------------------------------------------------------


def discover_jobs_for_date(target_date: date) -> List[NFLJob]:
    log.info(f"Discovering NFL jobs for {target_date}")

    # 1. Get Schedule from ESPN
    client = NFLScoreboardClient()
    games = client.fetch_schedule(target_date)

    # 2. Get Kalshi Events
    k_events = _fetch_kalshi_events()

    # Index Kalshi events by Suffix (Away+Home)
    # ESPN gives us Away and Home. Kalshi ticker is usually "YYMMDD" + Away + Home.
    # We will try to match flexibly.

    jobs = []

    for g in games:
        home = g["home_team"]
        away = g["away_team"]
        gid = g["game_id"]
        tipoff = g["tipoff_utc"]

        # Expected Kalshi suffixes
        # 1. AwayHome (Standard) e.g. TENCLE
        # 2. HomeAway (Rare but possible)
        # We search the list of events for one that contains the team codes

        matched_event = None
        for ke in k_events:
            et = ke.get("event_ticker", "")
            if not et:
                continue

            # Simple substring check: Does the ticker contain BOTH teams?
            # Warning: "NYG" contains "NY". "LAC" contains "LA". Be careful.
            # But in the suffix "TENCLE", "TEN" and "CLE" are distinct.

            # Robust Check:
            # Parse the ticker date to ensure we don't match a future game between same teams?
            # The NFL schedule rarely has same teams playing twice in a week.

            if home in et and away in et:
                matched_event = ke
                break

        if not matched_event:
            log.warning(f"No Kalshi event found for {away} @ {home}")
            continue

        market_tickers = _extract_winner_markets(matched_event)
        if len(market_tickers) != 2:
            continue

        job = NFLJob(
            game_date=target_date.isoformat(),
            game_id=gid,
            home_team=home,
            away_team=away,
            tipoff_utc=tipoff,
            event_ticker=matched_event["event_ticker"],
            market_tickers=market_tickers
        )
        jobs.append(job)

    log.info(f"Discovered {len(jobs)} NFL jobs.")
    return jobs


def _save_jobs(jobs: List[NFLJob], target_date: date):
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
