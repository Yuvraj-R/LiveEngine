# src/strategies/late_game_shock_fade.py

from typing import Any, Dict, List
from collections import deque
from datetime import datetime, timezone

from ..base.strategy import Strategy, TradeIntent


class LateGameShockFadeStrategy(Strategy):
    """
    Fade big late-game overreaction: if one side's price jumps
    a lot over a short window, buy the opposite side.
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        super().__init__(params)

        # Risk / timing
        self.stake: float = float(self.params.get("stake", 25.0))
        self.q_late: int = int(self.params.get("q_late", 4))
        self.t_late: float = float(self.params.get("t_late", 4.0))  # minutes
        self.max_score_diff: float = float(
            self.params.get("max_score_diff", 6.0))

        # Shock detection over a sliding time window
        self.window_seconds: float = float(
            self.params.get("window_seconds", 8.0))
        self.min_shock_move: float = float(
            self.params.get("min_shock_move", 0.15))
        self.max_delta_score_for_shock: float = float(
            self.params.get("max_delta_score_for_shock", 3.0)
        )
        self.min_spread_after_shock: float = float(
            self.params.get("min_spread_after_shock", 0.30)
        )

        # Price sanity bounds
        self.price_min: float = float(self.params.get("price_min", 0.01))
        self.price_max: float = float(self.params.get("price_max", 0.99))

    # -------------------------
    # Helpers
    # -------------------------

    def _parse_ts(self, ts_str: str) -> float:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    def _effective_open_price(self, m: Dict[str, Any]) -> float | None:
        """
        Mirror execution: pay ask if available, else mid, else bid.
        """
        yes_bid = m.get("yes_bid_prob")
        yes_ask = m.get("yes_ask_prob")
        mid = m.get("price")

        if yes_ask is not None:
            return yes_ask
        if mid is not None:
            return mid
        return yes_bid

    def _is_price_shock(
        self,
        history: deque[tuple[float, float]],
        current_price: float,
        ts_epoch: float,
    ) -> bool:
        """
        Sliding-window shock: price must move up by >= min_shock_move
        within window_seconds.
        """
        # prune old points
        cutoff = ts_epoch - self.window_seconds
        while history and history[0][0] < cutoff:
            history.popleft()

        if not history:
            return False

        first_ts, first_price = history[0]
        # window guaranteed <= window_seconds after prune
        delta_price = current_price - first_price
        return delta_price >= self.min_shock_move

    def _update_memory(
        self,
        game_mem: Dict[str, Any],
        markets: List[Dict[str, Any]],
        score_diff: float,
        ts_epoch: float,
    ) -> None:
        last_price: Dict[str, float] = game_mem.setdefault("last_price", {})
        price_history: Dict[str, deque] = game_mem.setdefault(
            "price_history", {})

        cutoff = ts_epoch - self.window_seconds

        for m in markets:
            if not (isinstance(m, dict) and m.get("type") == "moneyline"):
                continue

            p = self._effective_open_price(m)
            if p is None:
                continue

            mid = float(p)
            mid_id = m["market_id"]

            hist = price_history.setdefault(mid_id, deque())
            # prune old
            while hist and hist[0][0] < cutoff:
                hist.popleft()
            hist.append((ts_epoch, mid))

            last_price[mid_id] = mid

        game_mem["last_score_diff"] = score_diff

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
        game_id = state["game_id"]
        ts_iso: str = state["timestamp"]
        ts_epoch = self._parse_ts(ts_iso)

        games = self.state.setdefault("games", {})
        game_mem: Dict[str, Any] = games.setdefault(
            game_id,
            {
                "last_score_diff": None,
                "last_price": {},
                "price_history": {},
            },
        )

        last_score_diff = game_mem.get("last_score_diff")
        price_history: Dict[str, deque] = game_mem.setdefault(
            "price_history", {})

        in_window = (
            quarter >= self.q_late
            and time_remaining <= self.t_late
            and abs(score_diff) <= self.max_score_diff
        )

        if in_window and last_score_diff is not None:
            moneylines = [
                m
                for m in markets
                if isinstance(m, dict) and m.get("type") == "moneyline"
            ]
            positions = portfolio.get("positions", {})

            for m in moneylines:
                mid = self._effective_open_price(m)
                if mid is None:
                    continue

                mid = float(mid)
                m_id = m["market_id"]
                hist = price_history.setdefault(m_id, deque())

                # check sliding-window shock for this market (mutates hist by pruning)
                shocked = self._is_price_shock(hist, mid, ts_epoch)
                if not shocked:
                    continue

                # scoreboard change must be small between last tick and now
                if abs(score_diff - last_score_diff) > self.max_delta_score_for_shock:
                    continue

                # find opposite side market (assume 2 MLs)
                others = [mm for mm in moneylines if mm.get(
                    "market_id") != m_id]
                if len(others) != 1:
                    continue

                opp = others[0]
                opp_price = self._effective_open_price(opp)
                if opp_price is None:
                    continue
                opp_price = float(opp_price)

                spread = mid - opp_price
                if spread < self.min_spread_after_shock:
                    continue

                if not (self.price_min < opp_price < self.price_max):
                    continue

                opp_pos = positions.get(opp["market_id"])
                current_risk = opp_pos["dollars_at_risk"] if opp_pos else 0.0
                if current_risk != 0.0:
                    continue

                intents.append(
                    TradeIntent(
                        market_id=opp["market_id"],
                        action="open",
                        position_size=self.stake,
                    )
                )
                break  # one trade per tick

        # update memory after decisions
        self._update_memory(game_mem, markets, score_diff, ts_epoch)
        return intents
