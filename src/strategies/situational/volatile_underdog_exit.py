# src/strategies/situational/volatile_underdog_exit.py

from typing import Any, Dict, List
from ..base.strategy import Strategy, TradeIntent


class VolatileUnderdogExitStrategy(Strategy):
    """
    Buys the underdog late in a close game and attempts to exit 
    as soon as the position is up by a specific profit percentage (default 10%).
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        super().__init__(params)
        p = self.params

        # Entry Parameters (Same defaults as LateGameUnderdog)
        self.stake: float = float(p.get("stake", 100.0))
        self.max_price: float = float(p.get("max_price", 0.18))
        self.max_score_diff: float = float(p.get("max_score_diff", 6.0))
        self.min_time_remaining: float = float(
            p.get("min_time_remaining", 0.5))
        self.max_time_remaining: float = float(
            p.get("max_time_remaining", 5.0))
        self.min_quarter: int = int(p.get("min_quarter", 4))

        # Exit Parameters (Tunable)
        self.profit_target_pct: float = float(p.get("profit_target_pct", 0.10))

    def _effective_open_price(self, m: Dict[str, Any]) -> float | None:
        """
        Get the cost to buy YES.
        """
        yes_ask = m.get("yes_ask_prob")
        mid = m.get("price")
        yes_bid = m.get("yes_bid_prob")

        if yes_ask is not None:
            return float(yes_ask)
        if mid is not None:
            return float(mid)
        return yes_bid

    def on_state(
        self,
        state: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> List[TradeIntent]:
        intents: List[TradeIntent] = []

        quarter: int = state.get("quarter", 0)
        time_remaining: float = state.get("time_remaining_minutes", 0.0)
        # Using abs() for score diff to match "closeness" regardless of who is leading
        score_diff: float = abs(
            state.get("score_home", 0) - state.get("score_away", 0))
        markets = state.get("markets") or []
        positions = portfolio.get("positions", {})

        # ---------------------------------------------------------
        # 1. EXIT LOGIC: Monitor Existing Positions
        # ---------------------------------------------------------
        for mid, pos in positions.items():
            market_data = next(
                (m for m in markets if m["market_id"] == mid), None)
            if not market_data:
                continue

            # We exit based on the BID (the price we can actually sell at)
            current_bid = market_data.get("yes_bid_prob")
            if current_bid is None:
                continue

            entry_price = pos.get("entry_price", 0.0)
            if entry_price == 0:
                continue

            # Profit Calculation
            current_gain_pct = (current_bid - entry_price) / entry_price

            if current_gain_pct >= self.profit_target_pct:
                intents.append(
                    TradeIntent(
                        market_id=mid,
                        action="close",
                        position_size=pos["contracts"] * current_bid
                    )
                )

        # ---------------------------------------------------------
        # 2. ENTRY LOGIC: Evaluate New Underdogs
        # ---------------------------------------------------------
        in_window = (
            quarter >= self.min_quarter
            and self.min_time_remaining < time_remaining < self.max_time_remaining
            and score_diff <= self.max_score_diff
        )

        if not in_window:
            return intents

        for m in markets:
            if not (isinstance(m, dict) and m.get("type") == "moneyline"):
                continue

            p_eff = self._effective_open_price(m)
            # Standard underdog price filter
            if p_eff is None or not (0.01 < p_eff <= self.max_price):
                continue

            # Only open if we don't already have this market
            market_id = m["market_id"]
            if market_id not in positions:
                intents.append(
                    TradeIntent(
                        market_id=market_id,
                        action="open",
                        position_size=self.stake
                    )
                )

        return intents
