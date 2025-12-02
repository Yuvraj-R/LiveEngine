from typing import Any, Dict, List
from ..base.strategy import Strategy, TradeIntent


class TightGameCoinflipStrategy(Strategy):
    """
    Late-game, close-score coin-flip arb:
    - Only trade in crunch time.
    - Require game to be close.
    - Require both sides priced roughly like a coin flip.
    - Buy the cheaper side (lower effective probability).
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        super().__init__(params)

        # Tunable params (defaults are just starting points)
        self.q_crunch: int = self.params.get(
            "q_crunch", 4)          # quarter >= q_crunch
        self.t_crunch: float = self.params.get(
            "t_crunch", 4.0)      # minutes remaining <= t_crunch
        self.close_score_max: float = self.params.get("close_score_max", 5.0)

        # "coin flip" price band
        self.p_low: float = self.params.get("p_low", 0.35)
        self.p_high: float = self.params.get("p_high", 0.65)

        self.stake: float = self.params.get("stake", 25.0)

    # -------------------------
    # Internal helpers
    # -------------------------

    def _effective_open_price(self, m: Dict[str, Any]) -> float | None:
        """
        Mirror execution: for opening a YES position we effectively pay the ask,
        then mid, then bid.
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

        # Crunch-time + close score filter
        if not (quarter >= self.q_crunch and time_remaining <= self.t_crunch):
            return intents

        if abs(score_diff) > self.close_score_max:
            return intents

        # Collect moneyline markets with effective prices
        candidates: List[Dict[str, Any]] = []
        for m in markets:
            if not (isinstance(m, dict) and m.get("type") == "moneyline"):
                continue

            p_eff = self._effective_open_price(m)
            if p_eff is None:
                continue

            # Must look roughly like a coin flip
            if not (self.p_low <= p_eff <= self.p_high):
                continue

            m["_effective_open_price"] = p_eff
            candidates.append(m)

        if len(candidates) < 2:
            # Need both sides to be reasonably priced in the band
            return intents

        # Underdog here = cheaper side within the coin-flip band
        underdog = min(candidates, key=lambda m: m["_effective_open_price"])
        market_id = underdog["market_id"]
        implied = underdog["_effective_open_price"]

        # Only one open position per market
        positions = portfolio.get("positions", {})
        pos_info = positions.get(market_id)
        current_risk = pos_info["dollars_at_risk"] if pos_info else 0.0

        if current_risk == 0.0:
            intents.append(
                TradeIntent(
                    market_id=market_id,
                    action="open",
                    position_size=self.stake,
                )
            )

        return intents
