# src/engine/live_engine.py

from __future__ import annotations

from typing import Any, AsyncIterable, Dict

from src.engine.broker import BaseBroker
from src.strategies.strategy import Strategy


async def run_strategy_on_async_stream(
    strategy: Strategy,
    state_stream: AsyncIterable[Dict[str, Any]],
    broker: BaseBroker,
    *,
    max_states: int | None = None,
) -> BaseBroker:
    """
    Core live loop for Phase 3:
      - consume states from an async iterable
      - call strategy.on_state(state, portfolio_view)
      - hand TradeIntents to broker
    """
    n = 0

    async for state in state_stream:
        portfolio_view = broker.portfolio_view()
        intents = strategy.on_state(state, portfolio_view)

        if intents:
            broker.execute_intents(intents, state)

        broker.on_state_processed(state)

        n += 1
        if max_states is not None and n >= max_states:
            break

    return broker
