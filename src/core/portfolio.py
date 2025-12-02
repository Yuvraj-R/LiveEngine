# src/core/portfolio.py

from typing import Dict, List, Any

from src.core.models import Position, Trade


class PortfolioState:
    def __init__(self) -> None:
        self.cash: float = 0.0
        self.positions: Dict[str, Position] = {}
        self.trade_log: List[Trade] = []

    def get_portfolio_view(self, equity: float) -> Dict[str, Any]:
        """
        Returns strategy-facing snapshot.

        {
            "cash": float,
            "equity": float,
            "positions": {
                market_id: {
                    "dollars_at_risk": float,
                    "contracts": float,
                    "entry_price": float,
                },
                ...
            },
        }
        """
        positions_view: Dict[str, Dict[str, float]] = {}

        for mid, pos in self.positions.items():
            dollars_at_risk = pos.contracts * pos.entry_price
            positions_view[mid] = {
                "dollars_at_risk": dollars_at_risk,
                "contracts": pos.contracts,
                "entry_price": pos.entry_price,
            }

        return {
            "cash": self.cash,
            "equity": equity,
            "positions": positions_view,
        }
