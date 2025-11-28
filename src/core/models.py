from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict, Literal


# =========================
# Generic market / state
# =========================

class BaseMarket(TypedDict, total=False):
    """
    Generic snapshot of a Kalshi market at a point in time.
    Works for ANY domain (sports, elections, macro, etc.).
    """
    market_id: str              # usually Kalshi market ticker
    event_ticker: str           # parent event, if known

    # Generic classification (not tied to sports):
    # e.g. "binary", "scalar", "moneyline", "spread", "yes_no", etc.
    type: str

    # Price-level info (for binary-style markets, use probs in [0, 1])
    price: Optional[float]
    yes_bid_prob: Optional[float]
    yes_ask_prob: Optional[float]
    bid_ask_spread: Optional[float]

    volume: Optional[float]
    open_interest: Optional[float]

    status: Optional[str]       # "open", "closed", "settled", "finalized", ...
    result: Optional[str]       # "yes", "no", or domain-specific result

    # Arbitrary raw / metadata from Kalshi API
    meta: Dict[str, Any]


class BaseState(TypedDict, total=False):
    """
    Generic snapshot of "the world" at a time for an event:
      - a timestamp
      - some markets
      - optional extra context
    """
    timestamp: str              # ISO8601, UTC
    event_ticker: str

    markets: List[BaseMarket]

    # Domain-agnostic context, e.g.:
    #   - order book depth
    #   - election poll snapshot
    #   - macro indicators
    #   - etc.
    context: Dict[str, Any]


# =========================
# NBA-specialized children
# =========================

class NbaMoneylineMarket(BaseMarket, total=False):
    """
    NBA-specific extension for a moneyline-style market.
    All fields here are OPTIONAL and only populated for NBA domains.
    """
    team: Optional[str]                             # "LAL", "BOS", ...
    side: Optional[Literal["home", "away", "unknown"]]
    line: Optional[float]                           # if we ever care (spreads, etc.)


class NbaGameState(BaseState, total=False):
    """
    NBA-specific extension of BaseState with scoreboard info.
    Again, all optional; generic strategies shouldn't rely on these.
    """
    game_id: str
    home_team: str
    away_team: str

    score_home: float
    score_away: float
    score_diff: float          # home - away

    quarter: int
    time_remaining_minutes: float
    time_remaining_quarter_seconds: float


# =========================
# Portfolio views
# =========================

class PositionView(TypedDict, total=False):
    market_id: str
    contracts: float                 # positive for YES, negative for NO if needed
    dollars_at_risk: float
    avg_entry_price: Optional[float]

    # Arbitrary extra data (e.g. realized PnL, tags)
    meta: Dict[str, Any]


class PortfolioView(TypedDict, total=False):
    cash: float
    equity: float
    positions: Dict[str, PositionView]
