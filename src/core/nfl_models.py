# src/core/nfl_models.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from src.core.models import BaseMarket, BaseState

# =========================
# NFL-specialized markets
# =========================


class NFLMoneylineMarket(BaseMarket, total=False):
    """
    NFL-specific extension for a moneyline market.
    """
    team: Optional[str]                             # "KC", "BUF", ...
    side: Optional[Literal["home", "away", "unknown"]]
    # e.g. -2.5 if we track spreads later
    line: Optional[float]


# =========================
# NFL-specialized Game State
# =========================

class NFLGameState(BaseState, total=False):
    """
    The 'Merged' view of the world: One timestamp, one score, market prices.
    Includes deep context like Down, Distance, and Red Zone status.
    """
    game_id: str
    home_team: str
    away_team: str

    score_home: int
    score_away: int
    score_diff: int          # home - away

    quarter: int
    time_remaining_minutes: float
    time_remaining_quarter_seconds: float

    # --- NFL Context Fields ---
    possession_team: Optional[str]  # Abbreviation of team with ball
    down: int                       # 1, 2, 3, 4
    distance: int                   # Yards to go for 1st down
    # 0-100 scale (typically 100 = Opponent Endzone)
    yardline: int
    is_redzone: bool                # True if yardline >= 80 (inside 20)

    # "Last Play" context (useful for reaction strategies)
    last_play_text: Optional[str]


# =========================
# Scoreboard Snapshot (From ESPN)
# =========================

@dataclass
class NFLScoreboardSnapshot:
    """
    Raw snapshot from the NFL Data Provider (ESPN).
    """
    game_id: str
    home_team: str
    away_team: str

    score_home: int
    score_away: int

    quarter: int
    time_remaining_minutes: float
    time_remaining_quarter_seconds: float

    # Situational Data
    possession_team: Optional[str]
    down: int
    distance: int
    yardline: int

    # Metadata
    status: str                # "Scheduled", "In Progress", "Final"
    timestamp: datetime        # When we fetched this snapshot
    last_play: Optional[str]   # "Mahomes pass complete to Kelce for 8 yds"
    extra: Dict[str, Any]      # For raw JSON storage


# =========================
# Helper: Build State
# =========================

def build_nfl_state_dict(
    scoreboard: NFLScoreboardSnapshot,
    markets: Dict[str, NFLMoneylineMarket],
    *,
    event_ticker: Optional[str] = None,
    ts_iso: Optional[str] = None,
) -> NFLGameState:
    """
    Merge the Scoreboard Snapshot + Market Data into a final NFLGameState dict.
    """
    ts = ts_iso or scoreboard.timestamp.isoformat()

    # Derived Logic: Red Zone
    # Assuming yardline 0-100 where 100 is a touchdown.
    # (We will standardize this in the Connector).
    is_redzone = (scoreboard.yardline >= 80) if scoreboard.yardline else False

    score_diff = scoreboard.score_home - scoreboard.score_away

    state: NFLGameState = {
        "timestamp": ts,
        "event_ticker": event_ticker or "",
        "game_id": scoreboard.game_id,
        "home_team": scoreboard.home_team,
        "away_team": scoreboard.away_team,
        "score_home": scoreboard.score_home,
        "score_away": scoreboard.score_away,
        "score_diff": score_diff,

        "quarter": scoreboard.quarter,
        "time_remaining_minutes": scoreboard.time_remaining_minutes,
        "time_remaining_quarter_seconds": scoreboard.time_remaining_quarter_seconds,

        "possession_team": scoreboard.possession_team,
        "down": scoreboard.down,
        "distance": scoreboard.distance,
        "yardline": scoreboard.yardline,
        "is_redzone": is_redzone,
        "last_play_text": scoreboard.last_play,

        "markets": list(markets.values()),
        "context": {
            "nfl_raw": {
                "status": scoreboard.status,
                "timestamp": scoreboard.timestamp.isoformat(),
                "extra": scoreboard.extra,
            }
        },
    }
    return state
