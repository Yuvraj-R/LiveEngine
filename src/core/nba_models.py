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
    team: Optional[str]
    side: Optional[Literal["home", "away", "unknown"]]
    line: Optional[float]


class NBAGameState(BaseState, total=False):
    """
    Enriched NBA State.
    Now includes Possession, Fouls, Bonus, and Timeouts.
    """
    game_id: str
    home_team: str
    away_team: str

    score_home: float
    score_away: float
    score_diff: float

    quarter: int
    time_remaining_minutes: float
    time_remaining_quarter_seconds: float

    # --- NEW: Context Fields ---
    possession_team: Optional[str]  # "LAL", "BOS", or None (if dead ball)
    in_bonus_home: bool
    in_bonus_away: bool
    fouls_home: int
    fouls_away: int
    timeouts_home: int
    timeouts_away: int


# =========================
# Scoreboard snapshot
# =========================

@dataclass
class NBAScoreboardSnapshot:
    """
    Raw snapshot from NBA CDN.
    """
    game_id: str
    home_team: str
    away_team: str

    score_home: int
    score_away: int

    quarter: int
    time_remaining_minutes: float
    time_remaining_quarter_seconds: float

    status: str
    timestamp: datetime

    # --- NEW: Context Fields ---
    # Raw ID from API, converted to Abbrev later
    possession_team_id: Optional[str]
    in_bonus_home: bool
    in_bonus_away: bool
    fouls_home: int
    fouls_away: int
    timeouts_home: int
    timeouts_away: int

    extra: Dict[str, Any]


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

    ts = ts_iso or scoreboard.timestamp.isoformat()
    score_home = float(scoreboard.score_home)
    score_away = float(scoreboard.score_away)
    score_diff = score_home - score_away

    # Resolve Possession ID -> Abbreviation
    # The API gives us an ID (e.g., 1610612747). We need to check which team that is.
    # Note: We don't store team IDs in the Snapshot for Home/Away, only Abbrevs.
    # But usually we can map it via the scoreboard object or just pass it through if needed.
    # For now, let's try to map it if we can, or leave it as None if ambiguous.

    # Simple logic: We don't have the Team ID -> Abbrev map here easily unless we stored it.
    # But wait, the Scoreboard Client knows the IDs.
    # Let's assume the Client resolves it to an Abbreviation string before passing it here?
    # actually, let's make the Snapshot store the Abbreviation directly to simplify this function.
    # See updated Client code below.

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
        "time_remaining_quarter_seconds": float(scoreboard.time_remaining_quarter_seconds),

        # New Context
        # Client will populate this with ABBREV
        "possession_team": scoreboard.possession_team_id,
        "in_bonus_home": scoreboard.in_bonus_home,
        "in_bonus_away": scoreboard.in_bonus_away,
        "fouls_home": scoreboard.fouls_home,
        "fouls_away": scoreboard.fouls_away,
        "timeouts_home": scoreboard.timeouts_home,
        "timeouts_away": scoreboard.timeouts_away,

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
