from __future__ import annotations
from src.strategies.composite import CompositeStrategy
from src.strategies.registry import get_strategy_class
from src.core.trade_logger import TradeLogger
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

# Fix path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Dynamic Strategy Loading

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s][Worker-%(message)s]",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("worker")

JOBS_DIR = PROJECT_ROOT / "src" / "storage" / "jobs"
CONFIG_PATH = PROJECT_ROOT / "src" / "config" / "live_config.json"
PREGAME_MINUTES = 10


def _load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config not found at {CONFIG_PATH}")
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def _get_tipoff_from_job(game_date: str, event_ticker: str) -> datetime | None:
    jobs_path = JOBS_DIR / f"jobs_{game_date}.json"
    if not jobs_path.exists():
        return None
    try:
        with open(jobs_path, "r") as f:
            jobs = json.load(f)
        for job in jobs:
            if job.get("event_ticker") == event_ticker:
                tipoff_str = job.get("tipoff_utc")
                if tipoff_str:
                    return datetime.fromisoformat(tipoff_str)
    except Exception:
        pass
    return None


async def run_worker(
    event_ticker: str,
    game_id: str,
    home_team: str,
    away_team: str,
    market_tickers: list[str],
    game_date: str
):
    log.info(f"Initializing Worker | {away_team}@{home_team}")

    # 1. Load Configuration
    config = _load_config()
    trading_config = config.get("trading", {})

    # Check global mode vs CLI override (CLI override usually not passed by manager anymore)
    # We will trust the JSON config for "mode"
    mode_str = trading_config.get("mode", "dry_run").lower()
    is_dry_run = (mode_str != "live")

    # 2. Sleep Logic
    tipoff_dt = _get_tipoff_from_job(game_date, event_ticker)
    if tipoff_dt:
        start_time = tipoff_dt - timedelta(minutes=PREGAME_MINUTES)
        now = datetime.now(timezone.utc)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        sleep_secs = (start_time - now).total_seconds()
        if sleep_secs > 0:
            log.info(f"Tipoff {tipoff_dt}. Sleeping {sleep_secs:.0f}s...")
            await asyncio.sleep(sleep_secs)
            log.info("Waking up!")

    # 3. Setup Clients & Broker
    nba_client = NBAScoreboardClient()
    kalshi_http = KalshiHTTPClient()

    if is_dry_run:
        log.info("Mode: DRY RUN")
        broker = KalshiBroker(kalshi_http, dry_run=True)
    else:
        log.warning("Mode: LIVE REAL MONEY")
        broker = KalshiBroker(kalshi_http, dry_run=False)

    trade_logger = TradeLogger(dry_run=is_dry_run)

    # 4. Initialize Strategies from Config
    active_strats = []
    strat_configs = trading_config.get("active_strategies", [])

    for sc in strat_configs:
        if not sc.get("enabled", False):
            continue
        try:
            s_name = sc["name"]
            s_params = sc.get("params", {})
            Klass = get_strategy_class(s_name)
            instance = Klass(s_params)
            active_strats.append(instance)
            log.info(f"Loaded Strategy: {s_name}")
        except Exception as e:
            log.error(f"Failed to load strategy {sc.get('name')}: {e}")

    if not active_strats:
        log.error("No active strategies loaded! Worker will only record data.")
        # We continue anyway to ensure data is recorded

    # Wrap in Composite
    composite_strategy = CompositeStrategy(active_strats)
    engine = LiveEngine(composite_strategy, broker)
    state_writer = PredictEngineStateWriter(game_id)

    # 5. Streams
    target_dt = date.fromisoformat(game_date)
    nba_stream = nba_client.poll_game(
        game_id, poll_interval=2.0, stop_on_final=True, target_date=target_dt)
    k_stream = ticker_stream(market_tickers)
    merged_stream = merge_nba_and_kalshi_streams(
        event_ticker=event_ticker, game_id=game_id, home_team=home_team, away_team=away_team,
        tick_stream=k_stream, scoreboard_stream=nba_stream, initial_markets=market_tickers
    )

    # 6. Loop
    state_count = 0
    try:
        async for state in merged_stream:
            state_count += 1
            state_writer.append_state(state)

            try:
                portfolio_view = broker.get_portfolio_view()
                intents = composite_strategy.on_state(state, portfolio_view)

                for intent in intents:
                    # Execute
                    result = await broker.execute(intent, state)

                    # Get strategy name we attached in CompositeStrategy
                    strat_name = getattr(intent, 'strategy_name', 'unknown')

                    # Log to CSV
                    trade_logger.log_order_attempt(
                        game_id, strat_name, intent, result)

                    if result.ok:
                        log.info(
                            f"ORDER FILLED ({strat_name}): {intent.market_id} {intent.action}")
                    else:
                        log.error(
                            f"ORDER FAILED ({strat_name}): {result.error}")

            except Exception as e:
                log.error(f"Error in trading loop: {e}", exc_info=True)

            if state_count % 100 == 0:
                score = f"{state.get('score_away')}-{state.get('score_home')}"
                log.info(f"Heartbeat | Ticks: {state_count} | Score: {score}")

    except Exception as e:
        log.error(f"Worker crashed: {e}", exc_info=True)
    finally:
        state_writer.flush()
        log.info(f"Worker finished. Total states: {state_writer.count}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--event-ticker", required=True)
    p.add_argument("--game-id", required=True)
    p.add_argument("--home", required=True)
    p.add_argument("--away", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--markets", required=True)
    # Note: --dry-run is removed from CLI args because we use config.json now

    args = p.parse_args()
    market_list = args.markets.split(",")

    asyncio.run(run_worker(
        event_ticker=args.event_ticker,
        game_id=args.game_id,
        home_team=args.home,
        away_team=args.away,
        market_tickers=market_list,
        game_date=args.date
    ))
