# src/test/live_nba_kalshi_price_logger.py

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, date
from typing import Dict, List, Tuple

from src.connectors.kalshi.http_client import KalshiHTTPClient
from src.connectors.kalshi.ticker_stream import ticker_stream as kalshi_ticker_stream
from src.connectors.kalshi.nba_state_merger import merge_nba_and_kalshi_streams
from src.connectors.nba.scoreboard_client import NBAScoreboardClient, NBAScoreboardError

from src.engine.live_engine import LiveEngine
from src.engine.broker import KalshiBroker

from src.strategies.base.price_logger import PriceLoggerStrategy
from src.storage.state_writer import PredictEngineStateWriter

log = logging.getLogger(__name__)


# ------ helpers: parse event ticker → date + team codes ------

_MONTH_MAP: Dict[str, int] = {
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
}


def _parse_event_ticker(event_ticker: str) -> Tuple[date, str, str]:
    """
    KXNBAGAME-25DEC02WASPHI  ->  date(2025, 12, 2), away="WAS", home="PHI"
    """
    prefix = "KXNBAGAME-"
    if not event_ticker.startswith(prefix):
        raise ValueError(f"Unexpected event ticker format: {event_ticker}")

    body = event_ticker[len(prefix):]  # "25DEC02WASPHI"
    if len(body) < 13:
        raise ValueError(f"Unexpected event ticker body: {body}")

    date_part = body[:7]   # "25DEC02"
    teams_part = body[7:]  # "WASPHI"

    if len(teams_part) != 6:
        raise ValueError(f"Unexpected team suffix: {teams_part}")

    yy = int(date_part[0:2])      # "25"
    mon = date_part[2:5].upper()  # "DEC"
    dd = int(date_part[5:7])      # "02"

    if mon not in _MONTH_MAP:
        raise ValueError(f"Unknown month abbrev in ticker: {mon}")

    year = 2000 + yy
    month = _MONTH_MAP[mon]

    game_date = date(year, month, dd)

    away = teams_part[0:3].upper()
    home = teams_part[3:6].upper()

    return game_date, away, home


async def _resolve_game_from_event(
    event_ticker: str,
    nba_client: NBAScoreboardClient,
) -> tuple[str, str, str]:
    """
    Given a Kalshi NBA event ticker like KXNBAGAME-25DEC02WASPHI,
    resolve to (game_id, home_team, away_team) using the scoreboard for
    the date embedded in the ticker.
    """

    # 🌟 NEW: Parse the date and the team codes from the event ticker
    game_date, t1, t2 = _parse_event_ticker(event_ticker)

    team_set = {t1, t2}

    loop = asyncio.get_running_loop()

    # ❌ OLD: today_et = datetime.now(nba_client.tz).date()
    # ✅ NEW: Use the date from the ticker

    # Run the blocking nba_api call in a thread
    snaps = await loop.run_in_executor(
        None,
        nba_client.fetch_scoreboard_for_date,
        game_date,  # 🌟 Use game_date instead of today_et
    )

    matches: list[tuple[str, str, str]] = []
    for gid, snap in snaps.items():
        if {snap.home_team, snap.away_team} == team_set:
            matches.append((gid, snap.home_team, snap.away_team))

    if len(matches) == 1:
        gid, home_team, away_team = matches[0]
        return gid, home_team, away_team

    if not matches:
        raise NBAScoreboardError(
            f"Could not match event_ticker={event_ticker} to NBA game on "
            f"{game_date} (parsed teams: {t1}, {t2})"
        )

    # Extremely unlikely, but handle multiple games with same matchup
    raise NBAScoreboardError(
        f"Ambiguous matchup for event_ticker={event_ticker} on {game_date}: {matches}"
    )


# ------ main runner ------


async def run(event_ticker: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    log.info("[live_nba_price_logger] Starting for event %s", event_ticker)

    # 🟢 1. Parse date here immediately
    game_date, _, _ = _parse_event_ticker(event_ticker)

    http_client = KalshiHTTPClient()
    broker = KalshiBroker(client=http_client, dry_run=True)

    strategy = PriceLoggerStrategy()
    engine = LiveEngine(strategy=strategy, broker=broker)

    nba_client = NBAScoreboardClient()

    # Resolve game_id + teams from event ticker + scoreboard
    game_id, home_team, away_team = await _resolve_game_from_event(
        event_ticker, nba_client
    )

    log.info(
        "[live_nba_price_logger] Resolved event %s -> game_id=%s (%s @ %s) on %s",
        event_ticker,
        game_id,
        away_team,
        home_team,
        game_date
    )

    # Two Kalshi markets: home + away
    market_tickers: List[str] = [
        f"{event_ticker}-{home_team}",
        f"{event_ticker}-{away_team}",
    ]

    # Streams
    tick_stream = kalshi_ticker_stream(market_tickers=market_tickers)

    # 🟢 2. Pass the specific game date to the poller
    scoreboard_stream = nba_client.poll_game(
        game_id=game_id,
        target_date=game_date
    )

    merged_stream = merge_nba_and_kalshi_streams(
        game_id=game_id,
        home_team=home_team,
        away_team=away_team,
        tick_stream=tick_stream,
        scoreboard_stream=scoreboard_stream,
        initial_markets=market_tickers,
        event_ticker=event_ticker
    )

    state_writer: PredictEngineStateWriter | None = None

    async def wrapped_states():
        nonlocal state_writer
        async for state in merged_stream:
            if state_writer is None:
                gid = state.get("game_id") or game_id
                state_writer = PredictEngineStateWriter(game_id=gid)
                log.info(
                    "[live_nba_price_logger] Recording states for game %s to %s",
                    gid,
                    state_writer.path,
                )

            state_writer.append_state(state)
            yield state

    try:
        await engine.run(wrapped_states())
    finally:
        if state_writer is not None:
            state_writer.flush()
            log.info(
                "[live_nba_price_logger] Wrote %d states to %s",
                state_writer.count,
                state_writer.path,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--event-ticker",
        required=True,
        help="Kalshi event ticker, e.g. KXNBAGAME-25DEC02WASPHI",
    )
    args = parser.parse_args()
    asyncio.run(run(args.event_ticker))


if __name__ == "__main__":
    main()
