# src/core/nba_models.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from src.core.models import BaseMarket, BaseState


# =========================
# NBA-specialized markets / states
# =========================

class NBAMoneylineMarket(BaseMarket, total=False):
    """
    NBA-specific extension for a moneyline-style market.
    All fields here are OPTIONAL and only populated for NBA domains.
    """
    team: Optional[str]                             # "LAL", "BOS", ...
    side: Optional[Literal["home", "away", "unknown"]]
    line: Optional[float]                           # for spreads/totals later


class NBAGameState(BaseState, total=False):
    """
    NBA-specific extension of BaseState with scoreboard info.
    Strategies like LateGameUnderdog rely on these.
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
# Scoreboard snapshot used by NBA connector
# =========================

@dataclass
class NBAScoreboardSnapshot:
    """
    View of NBA scoreboard for a single game at a point in time.
    This is what NBAScoreboardClient produces.
    """
    game_id: str
    home_team: str
    away_team: str

    score_home: int
    score_away: int

    quarter: int
    time_remaining_minutes: float
    time_remaining_quarter_seconds: float

    status: str                # "1st Qtr", "Final", etc.
    timestamp: datetime        # when we fetched this snapshot
    extra: Dict[str, Any]      # reserved for future use


# =========================
# Helper to build engine-ready NBA state
# =========================

def build_nba_state_dict(
    scoreboard: NBAScoreboardSnapshot,
    markets: Dict[str, NBAMoneylineMarket],
    *,
    event_ticker: Optional[str] = None,
    ts_iso: Optional[str] = None,
) -> NBAGameState:
    """
    Convert a scoreboard snapshot + current markets into an NBAGameState
    that the live engine / strategies can consume.

    ts_iso:
      - if provided, use this as the 'timestamp' (e.g. Kalshi tick time)
      - else, fall back to scoreboard.timestamp
    """
    ts = ts_iso or scoreboard.timestamp.isoformat()

    score_home = float(scoreboard.score_home)
    score_away = float(scoreboard.score_away)
    score_diff = score_home - score_away

    state: NBAGameState = {
        "timestamp": ts,
        "event_ticker": event_ticker or "",
        "game_id": scoreboard.game_id,
        "home_team": scoreboard.home_team,
        "away_team": scoreboard.away_team,
        "score_home": score_home,
        "score_away": score_away,
        "score_diff": score_diff,
        "quarter": int(scoreboard.quarter),
        "time_remaining_minutes": float(scoreboard.time_remaining_minutes),
        "time_remaining_quarter_seconds": float(
            scoreboard.time_remaining_quarter_seconds
        ),
        "markets": list(markets.values()),
        "context": {
            "nba_raw": {
                "status": scoreboard.status,
                "timestamp": scoreboard.timestamp.isoformat(),
                "extra": scoreboard.extra,
            }
        },
    }
    return state
