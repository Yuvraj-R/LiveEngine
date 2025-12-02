# src/strategies/situational/deficit_recovery.py

from typing import Any, Dict, List
from ..base.strategy import Strategy, TradeIntent


class DeficitRecoveryStrategy(Strategy):
    """
    Bet on a team that has recovered from a large deficit to a close game,
    but is still priced as a heavy underdog.

    Default Rules (Tunable):
    - Team was previously down by >= 8 points (min_initial_deficit).
    - Team is now down by <= 4 points (max_current_deficit).
    - Market price is still <= 25% (max_price).
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        super().__init__(params)
        p = self.params

        self.stake: float = float(p.get("stake", 25.0))

        # Condition 1: How bad was it before? (e.g. 8, 10, 12)
        self.min_initial_deficit: float = float(
            p.get("min_initial_deficit", 8.0))

        # Condition 2: How close is it now? (e.g. 4)
        self.max_current_deficit: float = float(
            p.get("max_current_deficit", 4.0))

        # Condition 3: Is the price still cheap? (e.g. 0.25, 0.20, 0.15)
        self.max_price: float = float(p.get("max_price", 0.25))

        # Min price to avoid dead markets
        self.min_price: float = float(p.get("min_price", 0.01))

        # Memory to track the worst deficit each team has faced in the current game
        # Structure: { game_id: { "home_max_deficit": 12, "away_max_deficit": 5 } }
        self.state.setdefault("games", {})

    def _effective_open_price(self, m: Dict[str, Any]) -> float | None:
        """
        Get the cost to buy YES (Ask -> Mid -> Bid).
        """
        yes_ask = m.get("yes_ask_prob")
        mid = m.get("price")
        yes_bid = m.get("yes_bid_prob")

        if yes_ask is not None:
            return yes_ask
        if mid is not None:
            return mid
        return yes_bid

    def on_state(
        self,
        state: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> List[TradeIntent]:
        intents: List[TradeIntent] = []

        game_id = state["game_id"]
        score_home = state["score_home"]
        score_away = state["score_away"]
        markets = state.get("markets") or []

        # 1. Update Deficit Memory
        games_mem = self.state["games"]
        if game_id not in games_mem:
            games_mem[game_id] = {
                "home_max_deficit": 0.0, "away_max_deficit": 0.0}

        game_mem = games_mem[game_id]

        # Calculate current deficits (deficit is positive if trailing)
        home_deficit = score_away - score_home
        away_deficit = score_home - score_away

        # Update historical max deficits
        if home_deficit > game_mem["home_max_deficit"]:
            game_mem["home_max_deficit"] = home_deficit

        if away_deficit > game_mem["away_max_deficit"]:
            game_mem["away_max_deficit"] = away_deficit

        # 2. Check Conditions for both teams
        for m in markets:
            if not (isinstance(m, dict) and m.get("type") == "moneyline"):
                continue

            # Identify which team this market is for
            team = m.get("team")  # e.g. "GSW" or "SAS"
            side = m.get("side")  # "home" or "away" (if available)

            # Determine this team's specific deficit data
            if side == "home" or team == state.get("home_team"):
                curr_deficit = home_deficit
                worst_past_deficit = game_mem["home_max_deficit"]
            elif side == "away" or team == state.get("away_team"):
                curr_deficit = away_deficit
                worst_past_deficit = game_mem["away_max_deficit"]
            else:
                continue

            # CRITERIA CHECK:

            # A. Must be currently trailing (or tied), but within the close-game window
            #    (If they are winning, curr_deficit would be negative)
            if not (0.0 <= curr_deficit <= self.max_current_deficit):
                continue

            # B. Must have been down bad earlier
            if worst_past_deficit < self.min_initial_deficit:
                continue

            # C. Price check (Is it cheap?)
            p_eff = self._effective_open_price(m)
            if p_eff is None or not (self.min_price < p_eff <= self.max_price):
                continue

            # D. Risk Check (Don't double dip)
            market_id = m["market_id"]
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
