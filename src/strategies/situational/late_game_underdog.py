# src/strategies/late_game_underdog.py

from typing import Any, Dict, List
from ..base.strategy import Strategy, TradeIntent


class LateGameUnderdogStrategy(Strategy):
    """
    Buy the underdog moneyline late in the game when the score is close
    and the market is pessimistic. Let the position settle at game end.
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        super().__init__(params)
        p = self.params

        self.max_price: float = float(p.get("max_price", 0.15))
        self.stake: float = float(p.get("stake", 25.0))

        # NEW: tunable score + time window
        self.max_score_diff: float = float(p.get("max_score_diff", 6.0))
        self.min_time_remaining: float = float(
            p.get("min_time_remaining", 0.5))
        self.max_time_remaining: float = float(
            p.get("max_time_remaining", 5.0))
        self.min_quarter: int = int(p.get("min_quarter", 4))

    # -------------------------
    # Internal helpers
    # -------------------------

    def _effective_open_price(self, m: Dict[str, Any]) -> float | None:
        """
        Mirror execution: for opening a YES position we effectively pay the ask.
        Fallback to mid, then bid if needed.
        """
        yes_bid = m.get("yes_bid_prob")
        yes_ask = m.get("yes_ask_prob")
        mid = m.get("price")

        if yes_ask is not None:
            return yes_ask
        if mid is not None:
            return mid
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

        quarter: int = state["quarter"]
        time_remaining: float = state["time_remaining_minutes"]
        score_diff: float = state["score_diff"]
        markets = state.get("markets") or []

        # Tunable late-game, close-score filter
        if not (
            quarter >= self.min_quarter
            and self.min_time_remaining < time_remaining < self.max_time_remaining
        ):
            return intents

        # moneyline winner markets only, with usable execution price
        candidates: List[Dict[str, Any]] = []
        for m in markets:
            if not (isinstance(m, dict) and m.get("type") == "moneyline"):
                continue

            p_eff = self._effective_open_price(m)
            if p_eff is None or p_eff <= 0.0:
                continue

            m["_effective_open_price"] = p_eff
            candidates.append(m)

        if not candidates:
            return intents

        # Underdog = lowest effective execution price
        underdog = min(candidates, key=lambda m: m["_effective_open_price"])
        underdog_market_id = underdog["market_id"]
        implied_win_prob: float = underdog["_effective_open_price"]

        positions = portfolio.get("positions", {})
        pos_info = positions.get(underdog_market_id)
        current_risk = pos_info["dollars_at_risk"] if pos_info else 0.0

        if (
            score_diff <= self.max_score_diff
            and 0.01 < implied_win_prob < self.max_price
            and current_risk == 0.0  # max 1 open per market
        ):
            intents.append(
                TradeIntent(
                    market_id=underdog_market_id,
                    action="open",
                    position_size=self.stake,
                )
            )

        return intents
