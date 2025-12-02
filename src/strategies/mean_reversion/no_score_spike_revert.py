from typing import Any, Dict, List
from ..base.strategy import Strategy, TradeIntent


TERMINAL_STATUSES = {"finalized", "inactive", "settled", "closed"}


class NoScoreSpikeRevertStrategy(Strategy):
    """
    Fade big price spikes that happen with only small score-change:
    if one side's price jumps, buy the *other* side's moneyline.
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        super().__init__(params)

        # Minimum absolute move in implied prob to count as a "spike"
        self.spike_min_abs: float = self.params.get(
            "spike_min_abs", 0.08)  # 8pp

        # Max allowed absolute change in score differential between ticks
        # to still treat as "no meaningful score change"
        self.max_score_diff_change: float = self.params.get(
            "max_score_diff_change",
            0.0,  # 0.0 ≈ old behavior: exact same score
        )

        # Global price bounds to avoid trading at degenerate 0/1 probabilities
        self.price_min: float = self.params.get("price_min", 0.01)
        self.price_max: float = self.params.get("price_max", 0.99)

        self.stake: float = self.params.get("stake", 25.0)

        # internal memory:
        # self.state["last_score_diff"] = float
        # self.state["last_prices"] = {market_id: price}

    def _effective_price(self, m: Dict[str, Any]) -> float | None:
        """
        Mirror execution: for opening a YES position we effectively pay the ask.
        Fallback to mid, then bid if needed, and enforce price bounds.
        """
        yes_bid = m.get("yes_bid_prob")
        yes_ask = m.get("yes_ask_prob")
        mid = m.get("price")

        if yes_ask is not None:
            p = yes_ask
        elif mid is not None:
            p = mid
        else:
            p = yes_bid

        if p is None:
            return None

        # Enforce global bounds like (0.01, 0.99)
        if not (self.price_min <= p <= self.price_max):
            return None

        return p

    def _is_tradable_market(self, m: Dict[str, Any]) -> bool:
        status = m.get("status")
        if isinstance(status, str) and status.lower() in TERMINAL_STATUSES:
            return False
        return True

    def on_state(
        self,
        state: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> List[TradeIntent]:
        intents: List[TradeIntent] = []

        # moneyline + not terminal
        raw_markets = state.get("markets") or []
        markets = [
            m
            for m in raw_markets
            if isinstance(m, dict)
            and m.get("type") == "moneyline"
            and self._is_tradable_market(m)
        ]

        if len(markets) < 2:
            return intents

        curr_diff: float = float(state["score_diff"])
        last_diff = self.state.get("last_score_diff")
        last_prices: Dict[str, float] = self.state.get("last_prices", {})

        # current prices (bounded)
        curr_prices: Dict[str, float] = {}
        for m in markets:
            p = self._effective_price(m)
            if p is not None:
                curr_prices[m["market_id"]] = p

        if last_prices and last_diff is not None:
            # only react if score diff hasn't changed "too much"
            if abs(curr_diff - last_diff) <= self.max_score_diff_change:
                best_mkt_id = None
                best_delta = 0.0

                for m in markets:
                    mid = m["market_id"]
                    if mid not in curr_prices or mid not in last_prices:
                        continue
                    delta = curr_prices[mid] - last_prices[mid]
                    if abs(delta) > abs(best_delta):
                        best_delta = delta
                        best_mkt_id = mid

                if best_mkt_id is not None and abs(best_delta) >= self.spike_min_abs:
                    # assume exactly two ML markets per game
                    other_market = None
                    for m in markets:
                        if m["market_id"] != best_mkt_id:
                            other_market = m
                            break

                    if other_market is not None:
                        other_id = other_market["market_id"]

                        positions = portfolio.get("positions", {})
                        pos_info = positions.get(other_id)
                        current_risk = pos_info["dollars_at_risk"] if pos_info else 0.0

                        if current_risk == 0.0:
                            intents.append(
                                TradeIntent(
                                    market_id=other_id,
                                    action="open",
                                    position_size=self.stake,
                                )
                            )

        # update memory
        self.state["last_score_diff"] = curr_diff
        self.state["last_prices"] = curr_prices

        return intents
