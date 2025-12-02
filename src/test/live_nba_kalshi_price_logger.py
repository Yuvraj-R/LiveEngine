# src/test/live_nba_kalshi_price_logger.py
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, List

from src.connectors.kalshi.ticker_stream import ticker_stream
from src.strategies.price_logger import PriceLoggerStrategy


def _parse_event_ticker(event_ticker: str) -> tuple[str, str]:
    """
    KXNBAGAME-25DEC01CHABKN -> away=CHA, home=BKN
    """
    try:
        _, suffix = event_ticker.split("-", 1)
    except ValueError:
        raise ValueError(f"Bad event_ticker format: {event_ticker!r}")

    if len(suffix) < 13:
        raise ValueError(f"Suffix too short in event_ticker: {event_ticker!r}")

    away = suffix[7:10]
    home = suffix[10:13]
    return away, home


async def run_price_logger(event_ticker: str) -> None:
    away, home = _parse_event_ticker(event_ticker)
    market_tickers: List[str] = [
        f"{event_ticker}-{away}",
        f"{event_ticker}-{home}",
    ]

    print(
        f"[live_nba_kalshi_price_logger] Event={event_ticker}, "
        f"markets={market_tickers}"
    )

    strategy = PriceLoggerStrategy()
    # Minimal portfolio view; price logger shouldn't really care
    portfolio_view: Dict[str, Any] = {"positions": {}}

    async for tick in ticker_stream(market_tickers):
        # Build a minimal generic state
        market = {
            "market_id": tick["market_ticker"],
            "event_ticker": event_ticker,
            "type": "binary",
            "price": tick["price_prob"],
            "yes_bid_prob": tick["yes_bid_prob"],
            "yes_ask_prob": tick["yes_ask_prob"],
            "bid_ask_spread": None,
            "volume": tick["volume"],
            "open_interest": tick["open_interest"],
            "status": tick["status"],
            "result": None,
            "meta": {},
        }

        state = {
            "timestamp": tick["ts_iso"],
            "event_ticker": event_ticker,
            "markets": [market],
            "context": {},
        }

        # Strategy is responsible for printing whatever it wants
        intents = strategy.on_state(state, portfolio_view)

        # Sanity: if it ever did emit intents, just show them (no broker yet)
        if intents:
            print("[live_nba_kalshi_price_logger] INTENTS:", intents)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Log live Kalshi prices for an NBA moneyline event."
    )
    p.add_argument(
        "--event-ticker",
        required=True,
        help="Kalshi event ticker, e.g. KXNBAGAME-25DEC01CHABKN",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    asyncio.run(run_price_logger(args.event_ticker))


if __name__ == "__main__":
    main()
