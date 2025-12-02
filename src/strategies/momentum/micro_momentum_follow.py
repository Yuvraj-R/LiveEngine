# src/strategies/micro_momentum_follow.py

from typing import Any, Dict, List
from ..base.strategy import Strategy, TradeIntent

TERMINAL_STATUSES = {"finalized", "inactive", "settled", "closed"}


class MicroMomentumFollowStrategy(Strategy):
    """
    Follow slow, sustained price drifts when the scoreboard is mostly quiet.
    Only enter when the drifting side is still relatively cheap (underdog-ish).
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        super().__init__(params)

        # How many states in the lookback window
        self.window_states: int = self.params.get("window_states", 10)

        # Minimum net move in implied prob over that window
        self.min_trend_move: float = self.params.get("min_trend_move", 0.07)

        # Max allowed change in score_diff over the window
        self.max_score_diff_change_window: float = self.params.get(
            "max_score_diff_change_window",
            3.0,
        )

        # Global price bounds
        self.price_min: float = self.params.get("price_min", 0.05)
        self.price_max: float = self.params.get("price_max", 0.40)

        # Extra cap on starting price (entry must begin cheap)
        self.entry_max_price: float = self.params.get(
            "entry_max_price",
            self.price_max,
        )

        self.stake: float = self.params.get("stake", 25.0)

        # state["history"] = {market_id: [{"price": p, "score_diff": sd}]}
        self.state.setdefault("history", {})

    # ----------------- helpers -----------------

    def _effective_price(self, m: Dict[str, Any]) -> float | None:
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

        if not (self.price_min <= p <= self.price_max):
            return None

        return p

    def _is_tradable_market(self, m: Dict[str, Any]) -> bool:
        if m.get("type") != "moneyline":
            return False
        status = m.get("status")
        if isinstance(status, str) and status.lower() in TERMINAL_STATUSES:
            return False
        return True

    # ----------------- main hook -----------------

    def on_state(
        self,
        state: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> List[TradeIntent]:
        intents: List[TradeIntent] = []
        history: Dict[str, List[Dict[str, float]]] = self.state["history"]

        curr_score_diff = float(state["score_diff"])
        markets = [m for m in (state.get("markets") or [])
                   if self._is_tradable_market(m)]
        if not markets:
            return intents

        # Update per-market history with current price + score_diff
        for m in markets:
            mid = m["market_id"]
            p = self._effective_price(m)
            if p is None:
                continue

            h = history.setdefault(mid, [])
            h.append({"price": float(p), "score_diff": curr_score_diff})
            if len(h) > self.window_states:
                history[mid] = h[-self.window_states:]

        # Look for the best upward trend with quiet scoreboard,
        # where the price starts cheap and stays in our band.
        best_mid = None
        best_delta_p = 0.0

        for m in markets:
            mid = m["market_id"]
            h = history.get(mid)
            if not h or len(h) < self.window_states:
                continue

            first = h[0]
            last = h[-1]

            p_start = first["price"]
            p_end = last["price"]
            delta_p = p_end - p_start
            delta_sd = abs(last["score_diff"] - first["score_diff"])

            # Must be an upward drift
            if delta_p <= 0.0:
                continue

            # Require a decent-sized move
            if delta_p < self.min_trend_move:
                continue

            # Scoreboard mostly quiet over window
            if delta_sd > self.max_score_diff_change_window:
                continue

            # Only consider underdog-ish prices: start + end fairly cheap
            if not (self.price_min <= p_start <= self.entry_max_price):
                continue
            if not (self.price_min <= p_end <= self.price_max):
                continue

            if delta_p > best_delta_p:
                best_delta_p = delta_p
                best_mid = mid

        if best_mid is None:
            return intents

        # Only open if we don't already have risk on that market
        positions = portfolio.get("positions", {})
        pos_info = positions.get(best_mid)
        current_risk = pos_info["dollars_at_risk"] if pos_info else 0.0

        if current_risk == 0.0:
            intents.append(
                TradeIntent(
                    market_id=best_mid,
                    action="open",
                    position_size=self.stake,
                )
            )

        return intents
