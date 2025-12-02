from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class TradeIntent:
    market_id: str
    action: str           # "open" or "close"
    position_size: float  # dollars


class Strategy:
    def __init__(self, params: Dict[str, Any] | None = None):
        self.params = params or {}
        self.state: Dict[str, Any] = {}  # optional internal memory

    def on_state(
        self,
        state: Dict[str, Any],        # game-level state, incl. markets[]
        portfolio: Dict[str, Any],    # snapshot: cash, equity, positions
    ) -> List[TradeIntent]:
        """
        Called once per game state snapshot.
        Should return zero or more TradeIntent objects.
        """
        raise NotImplementedError
