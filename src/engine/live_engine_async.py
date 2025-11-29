from __future__ import annotations

from typing import AsyncIterator

from src.core.models import BaseState
from src.engine.broker import BaseBroker
from src.strategies.strategy import Strategy


async def run_strategy_on_async_stream(
    strategy: Strategy,
    states: AsyncIterator[BaseState],
    broker: BaseBroker,
) -> None:
    """
    Glue:
      - consume async BaseState stream
      - call strategy.on_state
      - forward intents to broker
    """
    async for state in states:
        portfolio_view = broker.get_portfolio_view()
        intents = strategy.on_state(state, portfolio_view)
        if intents:
            broker.execute(state, intents)
