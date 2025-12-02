# src/strategies/price_shock_momentum.py

from typing import Any, Dict, List
from ..base.strategy import Strategy, TradeIntent


class PriceShockMomentumStrategy(Strategy):
    """
    When a market's price jumps sharply between consecutive states,
    jump on the move and then exit on a fixed profit or loss.
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        super().__init__(params)

        self.stake: float = self.params.get("stake", 25.0)
        self.min_shock_move: float = self.params.get("min_shock_move", 0.10)
        self.take_profit_move: float = self.params.get(
            "take_profit_move", 0.10)
        self.stop_loss_move: float = self.params.get("stop_loss_move", 0.08)

        self.price_min: float = self.params.get("price_min", 0.01)
        self.price_max: float = self.params.get("price_max", 0.99)

        # internal memory
        self.state.setdefault("last_price", {})       # market_id -> last price
        # market_id -> entry price
        self.state.setdefault("entry_price", {})

    # -------------------------
    # Helpers
    # -------------------------

    def _effective_price(self, m: Dict[str, Any]) -> float | None:
        yes_bid = m.get("yes_bid_prob")
        yes_ask = m.get("yes_ask_prob")
        mid = m.get("price")

        if mid is not None:
            return mid
        if yes_ask is not None:
            return yes_ask
        return yes_bid

    # -------------------------
    # Strategy interface
    # -------------------------

    def on_state(
        self,
        state: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> List[TradeIntent]:
        intents: List[TradeIntent] = []

        markets = state.get("markets") or []
        last_price: Dict[str, float] = self.state["last_price"]
        entry_price: Dict[str, float] = self.state["entry_price"]
        positions = portfolio.get("positions", {})

        # 1) Manage existing positions: take profit or cut loss
        for mid, pos_info in positions.items():
            dollars_at_risk = pos_info.get("dollars_at_risk", 0.0)
            if dollars_at_risk <= 0.0:
                continue

            # find current market
            m = next((m for m in markets if m.get("market_id") == mid), None)
            if not m:
                continue

            p_curr = self._effective_price(m)
            p_entry = entry_price.get(mid)
            if p_curr is None or p_entry is None:
                continue

            move = p_curr - p_entry

            if move >= self.take_profit_move or move <= -self.stop_loss_move:
                intents.append(
                    TradeIntent(
                        market_id=mid,
                        action="close",
                        position_size=dollars_at_risk,
                    )
                )
                # after close, we can allow re-entry later
                entry_price.pop(mid, None)

        # 2) Look for fresh shocks and enter
        for m in markets:
            if not (isinstance(m, dict) and m.get("type") == "moneyline"):
                continue

            mid = m.get("market_id")
            p = self._effective_price(m)
            if p is None or not (self.price_min < p < self.price_max):
                continue

            prev = last_price.get(mid)
            last_price[mid] = p  # update for next tick

            # only enter if we have no open position in this market
            pos_info = positions.get(mid)
            if pos_info and pos_info.get("dollars_at_risk", 0.0) > 0.0:
                continue

            if prev is None:
                continue

            delta = p - prev

            # only follow strong upward shocks
            if delta >= self.min_shock_move:
                intents.append(
                    TradeIntent(
                        market_id=mid,
                        action="open",
                        position_size=self.stake,
                    )
                )
                entry_price[mid] = p

        return intents
