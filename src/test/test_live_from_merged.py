# src/test/test_live_from_merged.py

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List

from src.engine.broker import InMemoryBroker
from src.engine.live_engine import run_strategy_on_async_stream
from src.strategies.late_game_underdog import LateGameUnderdogStrategy
from src.test.helpers_merged_loader import load_merged_states


GAME_ID = "0022500292"  # <-- change to whatever file you copied in data/merged_states


async def _state_stream_from_list(states: List[Dict[str, Any]]) -> AsyncIterator[Dict[str, Any]]:
    """
    Async shim to feed a static list of states into the live engine.
    No artificial sleep for now; this is a fast offline replay.
    """
    for s in states:
        yield s


async def main() -> None:
    # 1) Load merged states from JSON
    states = load_merged_states(GAME_ID)
    print(f"[test] Loaded {len(states)} states for GAME_ID={GAME_ID}")

    # 2) Instantiate strategy + paper broker
    strategy = LateGameUnderdogStrategy(
        params={
            "stake": 25.0,
            "max_price": 0.20,
            "max_score_diff": 6.0,
            "min_time_remaining": 0.5,
            "max_time_remaining": 5.0,
            "min_quarter": 4,
        }
    )
    broker = InMemoryBroker(cash=5_000.0)

    # 3) Run the live engine over the async stream
    await run_strategy_on_async_stream(
        strategy=strategy,
        state_stream=_state_stream_from_list(states),
        broker=broker,
    )

    # 4) Print simple summary
    pv = broker.portfolio_view()
    print("\n=== FINAL PORTFOLIO VIEW ===")
    print(f"Cash: {pv['cash']:.2f}")
    print(f"Realized PnL: {broker.realized_pnl:.2f}")
    print(f"Open positions: {len(pv['positions'])}")

    print("\n=== TRADE LOG (first 10) ===")
    for entry in broker.trade_log[:10]:
        print(entry)

    print(f"\nTotal trades: {len(broker.trade_log)}")


if __name__ == "__main__":
    asyncio.run(main())
