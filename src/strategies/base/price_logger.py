# src/strategies/price_logger.py

from __future__ import annotations

from typing import Any, Dict, List

from src.strategies.base.strategy import Strategy, TradeIntent


class PriceLoggerStrategy(Strategy):
    """
    Debug strategy:
      - Logs markets + prices
      - Never sends any TradeIntent
    """

    def on_state(
        self,
        state: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> List[TradeIntent]:
        ts = state.get("timestamp")
        markets = state.get("markets") or []
        line = f"[PriceLogger] ts={ts}, markets="
        pieces = []
        for m in markets:
            if not isinstance(m, dict):
                continue
            mid = m.get("market_id")
            p = m.get("price")
            bid = m.get("yes_bid_prob")
            ask = m.get("yes_ask_prob")
            pieces.append(f"{mid}: p={p}, bid={bid}, ask={ask}")
        print(line + " | ".join(pieces))
        return []
