from __future__ import annotations

from typing import Iterable

from src.core.models import BaseState
from src.strategies.strategy import Strategy
from src.engine.broker import BaseBroker


def run_strategy_on_stream(
    strategy: Strategy,
    states: Iterable[BaseState],
    broker: BaseBroker,
) -> None:
    """
    Core synchronous loop:
      - pull state
      - build PortfolioView
      - call strategy.on_state
      - send intents to broker
    Later we can add logging, metrics, async wrappers, etc.
    """
    for state in states:
        # 1) snapshot portfolio
        portfolio_view = broker.get_portfolio_view()

        # 2) let strategy decide what to do
        intents = strategy.on_state(state, portfolio_view)

        # 3) hand intents to broker
        if intents:
            broker.execute(state, intents)
