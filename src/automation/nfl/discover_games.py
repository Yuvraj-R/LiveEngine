# src/automation/nfl/discover_games.py
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

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
SERIES_TICKER = "KXNFLGAME"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
JOBS_DIR = PROJECT_ROOT / "src" / "storage" / "jobs" / "nfl"

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("nfl_discover")

# --- MAPPING FIX ---
# Map ESPN Abbrev -> Kalshi Abbrev
ESPN_TO_KALSHI = {
    "JAX": "JAC",  # Jacksonville
    "WSH": "WAS",  # Washington
    "LAR": "LA",  # Rams
    "NO":  "NO",  # Saints (Explicit keep)
    "NE":  "NE",  # Patriots
    "GB":  "GB",  # Packers
    "KC":  "KC",  # Chiefs
    "TB":  "TB",  # Bucs
    "SF":  "SF",  # 49ers
    "LV":  "LV",  # Raiders
}


@dataclass
class NFLJob:
    game_date: str
    game_id: str
    home_team: str
    away_team: str
    tipoff_utc: Optional[str]
    event_ticker: str
    market_tickers: List[str]


def _fetch_kalshi_events() -> List[Dict[str, Any]]:
    url = f"{KALSHI_BASE_URL}/events"
    params = {"series_ticker": SERIES_TICKER,
              "with_nested_markets": "true", "status": "open", "limit": 200}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("events", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    except Exception as e:
        log.error(f"Failed to fetch Kalshi events: {e}")
        return []


def _extract_winner_markets(event: Dict[str, Any]) -> List[str]:
    markets = event.get("markets") or []
    tickers = []
    for m in markets:
        if m.get("market_type") == "binary" and "winner" in (m.get("title") or "").lower():
            if t := m.get("ticker"):
                tickers.append(t)
    return tickers


def discover_jobs_for_date(target_date: date) -> List[NFLJob]:
    log.info(f"Discovering NFL jobs for {target_date}")

    client = NFLScoreboardClient()
    games = client.fetch_schedule(target_date)
    k_events = _fetch_kalshi_events()

    jobs = []

    for g in games:
        home_espn = g["home_team"]
        away_espn = g["away_team"]

        # Normalize to Kalshi Format
        home_kalshi = ESPN_TO_KALSHI.get(home_espn, home_espn)
        away_kalshi = ESPN_TO_KALSHI.get(away_espn, away_espn)

        matched_event = None
        for ke in k_events:
            et = ke.get("event_ticker", "")
            if not et:
                continue

            # Robust Check: Look for the team codes in the ticker string
            # Kalshi tickers are like KXNFLGAME-25DEC07TENCLE
            # We check if BOTH normalized abbreviations exist in the ticker string.
            if home_kalshi in et and away_kalshi in et:
                matched_event = ke
                break

        if not matched_event:
            log.warning(
                f"No Kalshi event found for {away_espn} ({away_kalshi}) @ {home_espn} ({home_kalshi})")
            continue

        market_tickers = _extract_winner_markets(matched_event)
        if len(market_tickers) != 2:
            continue

        job = NFLJob(
            game_date=target_date.isoformat(),
            game_id=g["game_id"],
            home_team=home_espn,  # Keep ESPN ID for scoreboard polling compatibility
            away_team=away_espn,
            tipoff_utc=g["tipoff_utc"],
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
    d = date.fromisoformat(args.date) if args.date else datetime.now(
        ZoneInfo("America/New_York")).date()
    jobs = discover_jobs_for_date(d)
    _save_jobs(jobs, d)
