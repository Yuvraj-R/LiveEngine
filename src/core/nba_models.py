# src/core/nba_models.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, List

from src.core.models import BaseMarket, BaseState


# =========================
# NBA-specialized children
# =========================

class NBAMoneylineMarket(BaseMarket, total=False):
    """
    NBA-specific extension for a moneyline-style market.
    All fields here are OPTIONAL and only populated for NBA domains.
    """
    team: Optional[str]                             # "LAL", "BOS", ...
    side: Optional[Literal["home", "away", "unknown"]]
    # for spreads/totals later if needed
    line: Optional[float]


class NBAGameState(BaseState, total=False):
    """
    NBA-specific extension of BaseState with scoreboard info.
    Strategies like LateGameUnderdog can rely on these.
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
    Lightweight view of the NBA scoreboard for a single game at a point in time.
    Used by the NBA connector + Kalshi merger, not by strategies directly.
    """
    game_id: str
    home_team: str
    away_team: str

    # Current score (None if pre-game or not available)
    score_home: Optional[float] = None
    score_away: Optional[float] = None

    # Period / quarter info
    period: Optional[int] = None          # 1,2,3,4, OT=5, etc.
    # raw status string, e.g. "1Q", "Halftime", "Final"
    status: str = ""

    # Raw game clock string from API, if present
    game_clock: Optional[str] = None

    # Convenience flags / derived fields
    is_final: bool = False
    time_remaining_minutes: Optional[float] = None


# =========================
# Helper to build engine-ready NBA state
# =========================

def build_nba_state_dict(
    ts_iso: str,
    event_ticker: str,
    scoreboard: NBAScoreboardSnapshot,
    markets: List[NBAMoneylineMarket],
) -> NBAGameState:
    """
    Convert a scoreboard snapshot + current markets into an NBAGameState
    that the live engine / strategies can consume.
    """
    score_home = float(
        scoreboard.score_home) if scoreboard.score_home is not None else 0.0
    score_away = float(
        scoreboard.score_away) if scoreboard.score_away is not None else 0.0
    score_diff = score_home - score_away

    quarter = int(scoreboard.period) if scoreboard.period is not None else 0
    trm = float(
        scoreboard.time_remaining_minutes) if scoreboard.time_remaining_minutes is not None else 0.0

    state: NBAGameState = {
        "timestamp": ts_iso,
        "event_ticker": event_ticker,
        "game_id": scoreboard.game_id,
        "home_team": scoreboard.home_team,
        "away_team": scoreboard.away_team,
        "score_home": score_home,
        "score_away": score_away,
        "score_diff": score_diff,
        "quarter": quarter,
        "time_remaining_minutes": trm,
        "time_remaining_quarter_seconds": trm * 60.0,
        "markets": markets,
        "context": {
            "nba_raw": {
                "status": scoreboard.status,
                "game_clock": scoreboard.game_clock,
                "is_final": scoreboard.is_final,
            }
        },
    }
    return state
