# src/test/live_kalshi_ticker_debug.py

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List

from src.connectors.kalshi.ticker_stream import ticker_stream
from src.engine.broker import InMemoryBroker
from src.engine.live_engine import run_strategy_on_async_stream
from src.strategies.price_logger import PriceLoggerStrategy


# ---------------------------------------------------------------------
# CONFIG: fill these in with real livemarkets when games are live
# Example: two moneyline markets for one NBA game
#   "KXNBAGAME-25NOV24NYKBKN-NYK"
#   "KXNBAGAME-25NOV24NYKBKN-BKN"
# ---------------------------------------------------------------------
MARKET_TICKERS: List[str] = [
    "KXNBAGAME-25NOV29DALLAC-DAL"
]


async def _state_stream_from_tickers() -> AsyncIterator[Dict[str, Any]]:
    """
    Convert raw ticker events into minimal state dicts that the engine
    can consume. No NBA scoreboard yet; game_id is a placeholder.
    """
    async for ev in ticker_stream(MARKET_TICKERS):
        m = {
            "market_id": ev["market_ticker"],
            "type": "kalshi_generic",
            "price": ev.get("price_prob"),
            "yes_bid_prob": ev.get("yes_bid_prob"),
            "yes_ask_prob": ev.get("yes_ask_prob"),
            "volume": ev.get("volume"),
            "open_interest": ev.get("open_interest"),
            "status": ev.get("status"),
        }
        state = {
            "timestamp": ev["ts_iso"],
            "game_id": "LIVE_UNKNOWN",  # will become real GAME_ID in NBA integration
            "markets": [m],
        }
        yield state


async def main() -> None:
    if not MARKET_TICKERS:
        raise SystemExit(
            "Please set MARKET_TICKERS in live_kalshi_ticker_debug.py")

    strategy = PriceLoggerStrategy(params={})
    broker = InMemoryBroker(cash=1_000.0)

    print(f"[test-live] Starting live ticker debug for {MARKET_TICKERS}")

    await run_strategy_on_async_stream(
        strategy=strategy,
        state_stream=_state_stream_from_tickers(),
        broker=broker,
        # optional: cap number of states for testing
        # max_states=500,
    )


if __name__ == "__main__":
    asyncio.run(main())
