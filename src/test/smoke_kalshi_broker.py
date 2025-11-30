import asyncio
from typing import Any, Dict, AsyncIterator

from src.connectors.kalshi.http_client import KalshiHTTPClient
from src.engine.broker import KalshiBroker
from src.engine.live_engine import LiveEngine
from src.strategies.late_game_underdog import LateGameUnderdogStrategy
from src.strategies.strategy import TradeIntent


async def fake_state_stream() -> AsyncIterator[Dict[str, Any]]:
    # Minimal fake state with one moneyline market
    state: Dict[str, Any] = {
        "timestamp": "2025-11-25T01:23:45Z",
        "quarter": 4,
        "time_remaining_minutes": 2.0,
        "score_diff": 3.0,
        "markets": [
            {
                "market_id": "KXNBAGAME-FAKEEVENT-LAL",
                "type": "moneyline",
                "price": 0.15,
                "yes_bid_prob": 0.14,
                "yes_ask_prob": 0.16,
            }
        ],
    }
    yield state


async def main() -> None:
    strategy = LateGameUnderdogStrategy(
        {
            "max_price": 0.2,
            "stake": 25.0,
        }
    )

    client = KalshiHTTPClient()
    broker = KalshiBroker(client, dry_run=True)
    engine = LiveEngine(strategy, broker)

    await engine.run(fake_state_stream())

    print("KalshiBroker orders_log:")
    for rec in broker.orders_log:
        print(rec)


if __name__ == "__main__":
    asyncio.run(main())
