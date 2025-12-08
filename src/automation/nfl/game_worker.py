# src/automation/nfl/game_worker.py
from __future__ import annotations
from src.strategies.registry import get_strategy_class
from src.strategies.composite import CompositeStrategy
from src.core.trade_logger import TradeLogger
from src.storage.state_writer import PredictEngineStateWriter
from src.engine.live_engine import LiveEngine
from src.engine.broker import KalshiBroker
from src.connectors.nfl.scoreboard_client import NFLScoreboardClient
from src.connectors.kalshi.nfl_state_merger import merge_nfl_and_kalshi_streams
from src.connectors.kalshi.http_client import KalshiHTTPClient
from src.connectors.kalshi.ticker_stream import ticker_stream

import argparse
import asyncio
import logging
import sys
import json
import time
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

# Fix path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][NFL-Worker][%(message)s]",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("nfl_worker")

JOBS_DIR = PROJECT_ROOT / "src" / "storage" / "jobs" / "nfl"
NFL_STATES_DIR = PROJECT_ROOT / "src" / \
    "storage" / "kalshi" / "merged" / "nfl_states"

# --- CONFIG CHANGE ---
CONFIG_PATH = PROJECT_ROOT / "src" / "config" / "nfl_live_config.json"
# ---------------------

PREGAME_MINUTES = 30
TERMINAL_STATUSES = {"finalized", "settled", "closed"}


def _load_config():
    if not CONFIG_PATH.exists():
        return {}
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
                t = job.get("tipoff_utc")
                if t:
                    if t.endswith("Z"):
                        t = t[:-1] + "+00:00"
                    return datetime.fromisoformat(t)
    except:
        pass
    return None


async def _check_markets_terminal(http_client: KalshiHTTPClient, tickers: list[str]) -> bool:
    for t in tickers:
        try:
            resp = await asyncio.to_thread(http_client.get_market, t)
            status = (resp.get("market") or {}).get("status", "").lower()
            if status not in TERMINAL_STATUSES:
                return False
        except:
            return False
    return True


async def run_worker(
    event_ticker: str,
    game_id: str,
    home_team: str,
    away_team: str,
    market_tickers: list[str],
    game_date: str
):
    log.info(f"Init NFL Worker | {away_team}@{home_team} | {game_id}")

    # 1. Config & Sleep
    config = _load_config()
    trading_config = config.get("trading", {})
    mode_str = trading_config.get("mode", "dry_run").lower()
    is_dry_run = (mode_str != "live")

    tipoff_dt = _get_tipoff_from_job(game_date, event_ticker)
    if tipoff_dt:
        start_time = tipoff_dt - timedelta(minutes=PREGAME_MINUTES)
        now = datetime.now(timezone.utc)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        sleep_secs = (start_time - now).total_seconds()

        if sleep_secs > 0:
            log.info(f"Kickoff {tipoff_dt}. Sleeping {sleep_secs:.0f}s...")
            await asyncio.sleep(sleep_secs)
            log.info("Waking up!")
        else:
            log.info(
                f"Kickoff {tipoff_dt} was in the past. Starting immediately.")
    else:
        log.warning("No valid tipoff time found. Starting immediately.")

    # 2. Setup
    nfl_client = NFLScoreboardClient()
    kalshi_http = KalshiHTTPClient()

    if is_dry_run:
        log.info("Mode: DRY RUN")
        broker = KalshiBroker(kalshi_http, dry_run=True)
    else:
        log.warning("Mode: LIVE REAL MONEY")
        broker = KalshiBroker(kalshi_http, dry_run=False)

    # --- LOG SEPARATION ---
    trade_logger = TradeLogger(sport="nfl", dry_run=is_dry_run)
    # ----------------------

    # 3. Strategies
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

    composite_strategy = CompositeStrategy(active_strats)
    engine = LiveEngine(composite_strategy, broker)

    state_writer = PredictEngineStateWriter(game_id, output_dir=NFL_STATES_DIR)

    # 4. Streams
    target_dt = date.fromisoformat(game_date)
    nfl_stream = nfl_client.poll_game(
        game_id, poll_interval=1.0, stop_on_final=True)
    k_stream = ticker_stream(market_tickers)

    merged_stream = merge_nfl_and_kalshi_streams(
        event_ticker=event_ticker, game_id=game_id, home_team=home_team, away_team=away_team,
        tick_stream=k_stream, scoreboard_stream=nfl_stream, initial_markets=market_tickers
    )

    # 5. Loop
    state_count = 0
    last_rest_check = time.time()

    try:
        async for state in merged_stream:
            state_count += 1
            state_writer.append_state(state)

            # Exit Logic
            status = state.get("context", {}).get(
                "nfl_raw", {}).get("status", "")
            if "Final" in status:
                log.info("NFL Game Final. Exiting.")
                break

            if time.time() - last_rest_check > 60:
                if await _check_markets_terminal(kalshi_http, market_tickers):
                    log.info("Markets Closed. Exiting.")
                    break
                last_rest_check = time.time()

            # Trade Execution
            try:
                portfolio_view = broker.get_portfolio_view()
                intents = composite_strategy.on_state(state, portfolio_view)

                for intent in intents:
                    result = await broker.execute(intent, state)
                    strat_name = getattr(intent, 'strategy_name', 'unknown')
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

            if state_count % 300 == 0:
                log.info(
                    f"Heartbeat | Ticks: {state_count} | Score: {state.get('score_away')}-{state.get('score_home')}")

    except Exception as e:
        log.error(f"Worker crashed: {e}", exc_info=True)
    finally:
        state_writer.flush()
        log.info(f"Done. States written: {state_writer.count}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--event-ticker", required=True)
    p.add_argument("--game-id", required=True)
    p.add_argument("--home", required=True)
    p.add_argument("--away", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--markets", required=True)

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
