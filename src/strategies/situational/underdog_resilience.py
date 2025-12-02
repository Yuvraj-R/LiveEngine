from typing import Any, Dict, List
from ..base.strategy import Strategy, TradeIntent


class UnderdogResilienceStrategy(Strategy):
    """
    If a strong pre-game underdog is holding up well mid-game
    (close score, within specified quarter/time window),
    and the market is still pessimistic on them, buy the dog.
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        super().__init__(params)

        self.stake: float = self.params.get("stake", 25.0)

        # Pre-game dog threshold
        self.pregame_underdog_max: float = self.params.get(
            "pregame_underdog_max", 0.40)

        # Current in-game price threshold for dog
        self.current_underdog_max: float = self.params.get(
            "current_underdog_max", 0.45)

        # Game state window
        self.quarter_min: int = self.params.get("quarter_min", 2)
        self.quarter_max: int = self.params.get("quarter_max", 3)
        self.time_remaining_min: float = self.params.get(
            "time_remaining_min", 1.0)
        self.time_remaining_max: float = self.params.get(
            "time_remaining_max", 12.0)

        self.max_score_diff: float = self.params.get("max_score_diff", 6.0)

        self.price_min: float = self.params.get("price_min", 0.01)
        self.price_max: float = self.params.get("price_max", 0.99)

        # per-game memory
        self.state.setdefault("games", {})

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

    def _ensure_game(self, game_id: str, markets: List[Dict[str, Any]]):
        games = self.state["games"]
        if game_id in games:
            return games[game_id]

        ml = []
        for m in markets:
            if m.get("type") != "moneyline":
                continue
            p = self._effective_price(m)
            if p is None:
                continue
            m["_p0"] = p
            ml.append(m)

        if len(ml) < 2:
            info = {"skip": True}
            games[game_id] = info
            return info

        dog = min(ml, key=lambda x: x["_p0"])
        fav = max(ml, key=lambda x: x["_p0"])

        info = {
            "dog_id": dog["market_id"],
            "dog_pre": float(dog["_p0"]),
            "skip": False,
        }

        # require clear pre-game dog
        if info["dog_pre"] > self.pregame_underdog_max:
            info["skip"] = True

        games[game_id] = info
        return info

    # -------------------------

    def on_state(self, state, portfolio) -> List[TradeIntent]:
        intents: List[TradeIntent] = []

        game_id = state["game_id"]
        markets = state.get("markets") or []
        quarter = state["quarter"]
        t_rem = state["time_remaining_minutes"]
        score_diff = abs(state["score_diff"])

        info = self._ensure_game(game_id, markets)
        if info.get("skip"):
            return intents

        # quarter window
        if not (self.quarter_min <= quarter <= self.quarter_max):
            return intents

        # time remaining window
        if not (self.time_remaining_min <= t_rem <= self.time_remaining_max):
            return intents

        # score close enough
        if score_diff > self.max_score_diff:
            return intents

        # find dog market
        dog_id = info["dog_id"]
        dog = next((m for m in markets if m.get("market_id") == dog_id), None)
        if not dog:
            return intents

        p = self._effective_price(dog)
        if p is None or not (self.price_min < p < self.price_max):
            return intents

        # must still be priced like an underdog in-game
        if p > self.current_underdog_max:
            return intents

        # ensure price hasn't shot up too high relative to pregame
        if p > info["dog_pre"] + 0.10:
            return intents

        # no double-entry
        pos = portfolio.get("positions", {}).get(dog_id)
        if pos and pos.get("dollars_at_risk", 0.0) > 0.0:
            return intents

        intents.append(
            TradeIntent(
                market_id=dog_id,
                action="open",
                position_size=self.stake,
            )
        )

        return intents
