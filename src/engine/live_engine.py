from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict

from .broker import Broker
from src.strategies.strategy import Strategy

log = logging.getLogger(__name__)


class LiveEngine:
    """
    Minimal live engine:
      - consumes a stream of state dicts (merged game states, etc.)
      - runs a single Strategy
      - forwards TradeIntents to a Broker
    """

    def __init__(self, strategy: Strategy, broker: Broker) -> None:
        self.strategy = strategy
        self.broker = broker

    async def run(self, states: AsyncIterator[Dict[str, Any]]) -> None:
        async for state in states:
            try:
                portfolio_view = self.broker.get_portfolio_view()
                intents = self.strategy.on_state(state, portfolio_view)
            except Exception as e:  # noqa: BLE001
                log.exception("Strategy on_state error: %s", e)
                continue

            if not intents:
                continue

            for intent in intents:
                try:
                    _ = await self.broker.execute(intent, state)
                except Exception as e:  # noqa: BLE001
                    log.exception("Broker execute error: %s", e)
