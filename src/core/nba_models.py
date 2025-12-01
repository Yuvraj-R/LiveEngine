# src/core/nba_models.py

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from src.core.models import MarketSnapshot


@dataclass
class NBAMoneylineMarket(MarketSnapshot):
    """
    NBA moneyline view on top of a generic MarketSnapshot.
    """
    team: Optional[str] = None           # e.g. "BOS"
    side: str = "unknown"                # "home" | "away" | "unknown"


@dataclass
class NBAScoreboardSnapshot:
    """
    Live scoreboard view for one NBA game at a point in time.
    """
    game_id: str
    home_team: str
    away_team: str

    score_home: int
    score_away: int

    quarter: int                         # 0 if pre-game
    time_remaining_minutes: float        # approximate, whole-game minutes
    time_remaining_quarter_seconds: float

    status: str                          # e.g. "1st Qtr", "Final"
    timestamp: datetime

    extra: Dict[str, Any] = field(default_factory=dict)


def build_nba_state_dict(
    scoreboard: NBAScoreboardSnapshot,
    markets: Dict[str, NBAMoneylineMarket],
) -> Dict[str, Any]:
    """
    Adapt NBA scoreboard + markets into the dict-shaped state
    expected by backtest / strategies (late_game_underdog etc.).
    """
    score_diff = float(scoreboard.score_home - scoreboard.score_away)

    markets_list: list[Dict[str, Any]] = []
    for m in markets.values():
        markets_list.append(
            {
                "market_id": m.market_id,
                "type": "moneyline",
                "team": getattr(m, "team", None),
                "side": getattr(m, "side", "unknown"),
                "price": m.last_prob,
                "yes_bid_prob": m.yes_bid_prob,
                "yes_ask_prob": m.yes_ask_prob,
                "volume": m.volume,
                "open_interest": m.open_interest,
                "status": m.status,
            }
        )

    state: Dict[str, Any] = {
        "timestamp": scoreboard.timestamp.isoformat(),
        "game_id": scoreboard.game_id,
        "home_team": scoreboard.home_team,
        "away_team": scoreboard.away_team,
        "score_home": float(scoreboard.score_home),
        "score_away": float(scoreboard.score_away),
        "score_diff": score_diff,
        "quarter": int(scoreboard.quarter),
        "time_remaining_minutes": float(scoreboard.time_remaining_minutes),
        "time_remaining_quarter_seconds": float(
            scoreboard.time_remaining_quarter_seconds
        ),
        "markets": markets_list,
    }

    # allow future extensions
    state.update(scoreboard.extra or {})

    return state
