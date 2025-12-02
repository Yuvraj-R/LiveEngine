# src/strategies/panic_spread_fade.py

from typing import Any, Dict, List
from ..base.strategy import Strategy, TradeIntent


class PanicSpreadFadeStrategy(Strategy):
    """
    Detect a spread + price panic on one side, then fade it:
    - Watch bid/ask spread + price over a rolling window.
    - When spread blows out and price rips up on one side ("panic side"),
      start watching that side.
    - As soon as the panic-side price stops making new highs (first
      tick where price <= last panic price), buy the OPPOSITE side.
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        super().__init__(params)
        self.stake: float = float(self.params.get("stake", 25.0))
        self.spread_window: int = int(self.params.get("spread_window", 20))
        self.spread_spike_min: float = float(
            self.params.get("spread_spike_min", 0.05))
        self.spread_spike_factor: float = float(
            self.params.get("spread_spike_factor", 2.0))
        self.min_price_jump: float = float(
            self.params.get("min_price_jump", 0.05))
        self.min_quarter: int = int(self.params.get("min_quarter", 2))
        self.price_min: float = float(self.params.get("price_min", 0.01))
        self.price_max: float = float(self.params.get("price_max", 0.99))

        # state["market_state"][market_id] = {
        #   "recent_spreads": [...],
        #   "recent_prices": [...],
        #   "panic_active": bool,
        #   "panic_last_price": float | None,
        #   "panic_opp_market_id": str | None,
        # }
        self.state.setdefault("market_state", {})

    # ---- helpers -----------------------------------------------------

    def _effective_price(self, m: Dict[str, Any]) -> float | None:
        """
        Single scalar price to use for detection:
        prefer mid, then ask, then bid.
        """
        mid = m.get("price")
        ask = m.get("yes_ask_prob")
        bid = m.get("yes_bid_prob")
        for v in (mid, ask, bid):
            if v is not None:
                return float(v)
        return None

    def _find_opp_market_id(
        self,
        markets: List[Dict[str, Any]],
        market_id: str,
    ) -> str | None:
        """
        For now we assume exactly 2 moneyline markets for the game:
        the opposite side is "the other one".
        """
        moneylines = [
            m for m in markets
            if isinstance(m, dict) and m.get("type") == "moneyline"
        ]
        if len(moneylines) != 2:
            return None

        ids = [m.get("market_id") for m in moneylines]
        if market_id not in ids:
            return None

        other_ids = [mid for mid in ids if mid != market_id]
        return other_ids[0] if len(other_ids) == 1 else None

    # ---- main interface ----------------------------------------------

    def on_state(
        self,
        state: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> List[TradeIntent]:
        intents: List[TradeIntent] = []

        quarter: int = int(state.get("quarter", 0))
        if quarter < self.min_quarter:
            return intents

        markets = [
            m for m in (state.get("markets") or [])
            if isinstance(m, dict) and m.get("type") == "moneyline"
        ]
        if not markets:
            return intents

        market_state: Dict[str, Dict[str, Any]] = self.state["market_state"]

        # Index markets by id for fast lookup
        by_id: Dict[str, Dict[str, Any]] = {}
        for m in markets:
            mid = m.get("market_id")
            if not mid:
                continue
            by_id[mid] = m

        # 1) Update rolling history for all markets
        for m in markets:
            mid = m.get("market_id")
            if not mid:
                continue

            ms = market_state.setdefault(
                mid,
                {
                    "recent_spreads": [],
                    "recent_prices": [],
                    "panic_active": False,
                    "panic_last_price": None,
                    "panic_opp_market_id": None,
                },
            )

            spread = m.get("bid_ask_spread")
            price = self._effective_price(m)

            if spread is not None:
                rs = ms["recent_spreads"]
                rs.append(float(spread))
                if len(rs) > self.spread_window:
                    rs.pop(0)

            if price is not None:
                rp = ms["recent_prices"]
                rp.append(float(price))
                if len(rp) > self.spread_window:
                    rp.pop(0)

        positions = portfolio.get("positions", {})

        # 2) For any *existing* panic, see if price has stopped making new highs
        for mid, ms in list(market_state.items()):
            if not ms.get("panic_active"):
                continue

            m = by_id.get(mid)
            if not m:
                continue

            price = self._effective_price(m)
            if price is None:
                continue

            last_panic_price = ms.get("panic_last_price")
            if last_panic_price is None:
                ms["panic_last_price"] = price
                continue

            # Still ripping up → update peak and keep waiting
            if price > last_panic_price:
                ms["panic_last_price"] = price
                continue

            # First tick where price <= last_panic_price → time to fade
            opp_id = ms.get("panic_opp_market_id")
            if not opp_id:
                opp_id = self._find_opp_market_id(markets, mid)
                ms["panic_opp_market_id"] = opp_id

            if not opp_id:
                # Can't find clean opposite; drop panic
                ms["panic_active"] = False
                continue

            opp_m = by_id.get(opp_id)
            if not opp_m:
                ms["panic_active"] = False
                continue

            opp_price = self._effective_price(opp_m)
            if opp_price is None:
                ms["panic_active"] = False
                continue

            # Enforce price band
            if not (self.price_min <= opp_price <= self.price_max):
                ms["panic_active"] = False
                continue

            # One open position per market max
            pos = positions.get(opp_id)
            if pos and pos.get("dollars_at_risk", 0.0) > 0.0:
                ms["panic_active"] = False
                continue

            intents.append(
                TradeIntent(
                    market_id=opp_id,
                    action="open",
                    position_size=self.stake,
                )
            )
            ms["panic_active"] = False  # consume this panic

        # 3) Detect *new* panics (only when not already active)
        for m in markets:
            mid = m.get("market_id")
            if not mid:
                continue

            ms = market_state[mid]

            # skip if already in an active panic lifecycle
            if ms.get("panic_active"):
                continue

            spreads = ms["recent_spreads"]
            prices = ms["recent_prices"]
            spread = m.get("bid_ask_spread")
            price = self._effective_price(m)

            if (
                spread is None
                or price is None
                or len(spreads) < 3
                or len(prices) < 3
            ):
                continue

            avg_spread = sum(spreads[:-1]) / max(len(spreads) - 1, 1)
            if avg_spread <= 0.0:
                continue

            curr_spread = float(spread)
            old_price = float(prices[0])
            curr_price = float(price)

            # Spread must be absolutely wide AND relatively wide vs history
            if curr_spread < self.spread_spike_min:
                continue
            if curr_spread < self.spread_spike_factor * avg_spread:
                continue

            # Price must have ripped up enough over the window
            if curr_price - old_price < self.min_price_jump:
                continue

            # Lock in this as the initial panic state
            opp_id = self._find_opp_market_id(markets, mid)
            if not opp_id:
                continue

            ms["panic_active"] = True
            ms["panic_last_price"] = curr_price
            ms["panic_opp_market_id"] = opp_id

        return intents
