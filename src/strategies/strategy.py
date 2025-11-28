from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.core.models import BaseState, PortfolioView


@dataclass
class TradeIntent:
    """
    Generic instruction from a Strategy to the engine.

    - market_id: target Kalshi market
    - action:    "open", "close", "reduce", etc.
    - position_size: dollar stake (engine decides contracts / side details)
    """
    market_id: str
    action: str
    position_size: float


class Strategy:
    """
    Base Strategy interface.

    Backtest AND live trading will both call:

        on_state(state, portfolio_view) -> List[TradeIntent]

    `state` is a BaseState; domain-specific strategies may EXPECT that
    it's actually an NbaGameState, ElectionState, etc.
    """

    def __init__(self, params: Dict[str, Any] | None = None) -> None:
        self.params: Dict[str, Any] = params or {}

    def on_state(
        self,
        state: BaseState,
        portfolio: PortfolioView,
    ) -> List[TradeIntent]:
        raise NotImplementedError
