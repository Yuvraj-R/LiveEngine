from __future__ import annotations
from src.strategies.situational.deficit_recovery import DeficitRecoveryStrategy
from src.storage.state_writer import PredictEngineStateWriter
from src.engine.live_engine import LiveEngine
from src.engine.broker import KalshiBroker
from src.connectors.nba.scoreboard_client import NBAScoreboardClient
from src.connectors.kalshi.nba_state_merger import merge_nba_and_kalshi_streams
from src.connectors.kalshi.http_client import KalshiHTTPClient
from src.connectors.kalshi.ticker_stream import ticker_stream

import argparse
import asyncio
import logging
import sys
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

# Fix path to allow running as module
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Strategies

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s][Worker-%(message)s]",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("worker")

JOBS_DIR = PROJECT_ROOT / "src" / "storage" / "jobs"
PREGAME_MINUTES = 10  # Start streaming 10 mins before tip


def _get_tipoff_from_job(game_date: str, event_ticker: str) -> datetime | None:
    """
    Reads the jobs file for the given date and returns the tipoff time as a datetime object.
    """
    jobs_path = JOBS_DIR / f"jobs_{game_date}.json"
    if not jobs_path.exists():
        log.warning(f"Jobs file not found at {jobs_path}")
        return None

    try:
        with open(jobs_path, "r") as f:
            jobs = json.load(f)

        for job in jobs:
            if job.get("event_ticker") == event_ticker:
                tipoff_str = job.get("tipoff_utc")
                if tipoff_str:
                    return datetime.fromisoformat(tipoff_str)
    except Exception as e:
        log.error(f"Error reading job file: {e}")

    return None


async def run_worker(
    event_ticker: str,
    game_id: str,
    home_team: str,
    away_team: str,
    market_tickers: list[str],
    game_date: str,
    dry_run: bool = True
):
    log.info(
        f"Initializing Worker | Game: {away_team}@{home_team} | ID: {game_id}")

    # -----------------------------------------------------------------------
    # 0. Sleep until Pre-Game
    # -----------------------------------------------------------------------
    tipoff_dt = _get_tipoff_from_job(game_date, event_ticker)

    if tipoff_dt:
        start_time = tipoff_dt - timedelta(minutes=PREGAME_MINUTES)
        now = datetime.now(timezone.utc)

        # Ensure we are comparing offset-aware datetimes
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        sleep_secs = (start_time - now).total_seconds()

        if sleep_secs > 0:
            log.info(
                f"Tipoff is {tipoff_dt}. Sleeping {sleep_secs:.0f}s until pre-game window...")
            await asyncio.sleep(sleep_secs)
            log.info("Waking up! Starting streams.")
        else:
            log.info("Game is already imminent or started. Launching immediately.")
    else:
        log.warning("No tipoff time found in job. Launching immediately.")

    # -----------------------------------------------------------------------
    # 1. Setup Infrastructure
    # -----------------------------------------------------------------------

    # Initialize Clients
    nba_client = NBAScoreboardClient()
    kalshi_http = KalshiHTTPClient()

    # Broker Selection
    if dry_run:
        log.info("Mode: DRY RUN (Real API, No Trades)")
        broker = KalshiBroker(kalshi_http, dry_run=True)
    else:
        log.warning("Mode: LIVE REAL MONEY")
        broker = KalshiBroker(kalshi_http, dry_run=False)

    # Strategy Selection
    strategy = DeficitRecoveryStrategy({
        "stake": 25.0,
        "min_initial_deficit": 8.0,
        "max_current_deficit": 4.0,
        "max_price": 0.35,
        "min_price": 0.02
    })
    log.info(f"Strategy: {strategy.__class__.__name__}")

    # Engine
    engine = LiveEngine(strategy, broker)

    # Storage
    state_writer = PredictEngineStateWriter(game_id)
    log.info(f"State Writer initialized for {game_id}")

    # -----------------------------------------------------------------------
    # 2. Data Streams
    # -----------------------------------------------------------------------

    # NBA Stream (Polls every 2s)
    target_dt = date.fromisoformat(game_date)
    nba_stream = nba_client.poll_game(
        game_id,
        poll_interval=2.0,
        stop_on_final=True,
        target_date=target_dt
    )

    # Kalshi Stream (WebSocket)
    k_stream = ticker_stream(market_tickers)

    # Merger
    merged_stream = merge_nba_and_kalshi_streams(
        event_ticker=event_ticker,
        game_id=game_id,
        home_team=home_team,
        away_team=away_team,
        tick_stream=k_stream,
        scoreboard_stream=nba_stream,
        initial_markets=market_tickers
    )

    # -----------------------------------------------------------------------
    # 3. Main Event Loop
    # -----------------------------------------------------------------------
    state_count = 0
    try:
        async for state in merged_stream:
            state_count += 1

            # A. Persist State
            state_writer.append_state(state)

            # B. Execute Trading Logic
            try:
                portfolio_view = broker.get_portfolio_view()
                intents = strategy.on_state(state, portfolio_view)

                for intent in intents:
                    log.info(f"TRADE INTENT: {intent}")
                    result = await broker.execute(intent, state)
                    if result.ok:
                        log.info(
                            f"Order Executed: {result.order_id or 'DryRun'}")
                    else:
                        log.error(f"Order Failed: {result.error}")

            except Exception as e:
                log.error(f"Error in strategy/broker step: {e}", exc_info=True)

            if state_count % 100 == 0:
                score = f"{state.get('score_away')}-{state.get('score_home')}"
                log.info(f"Heartbeat | Ticks: {state_count} | Score: {score}")

    except Exception as e:
        log.error(f"Worker crashed: {e}", exc_info=True)
    finally:
        state_writer.flush()
        log.info(
            f"Worker finished. Total states written: {state_writer.count}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--event-ticker", required=True)
    p.add_argument("--game-id", required=True)
    p.add_argument("--home", required=True)
    p.add_argument("--away", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--markets", required=True,
                   help="Comma-separated market tickers")
    p.add_argument("--dry-run", action="store_true", default=False)

    args = p.parse_args()
    market_list = args.markets.split(",")

    asyncio.run(run_worker(
        event_ticker=args.event_ticker,
        game_id=args.game_id,
        home_team=args.home,
        away_team=args.away,
        market_tickers=market_list,
        game_date=args.date,
        dry_run=args.dry_run
    ))
