# src/connectors/nba/scoreboard_client.py

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Optional, AsyncIterator

from zoneinfo import ZoneInfo
from nba_api.stats.endpoints import scoreboardv2
from nba_api.stats.static import teams

from src.core.nba_models import NBAScoreboardSnapshot


class NBAScoreboardError(RuntimeError):
    pass


@dataclass
class NBAGameKey:
    game_id: str
    home_team: str
    away_team: str


def _parse_live_clock(header_row: Dict[str, object]) -> tuple[int, float]:
    """
    Derive (quarter, time_remaining_quarter_seconds).

    This uses LIVE_PERIOD and LIVE_PC_TIME if present.
    If parsing fails, we fall back to quarter=0, time=0.
    """
    quarter = 0
    raw_period = header_row.get("LIVE_PERIOD")
    try:
        if raw_period is not None:
            quarter = int(raw_period)
    except (TypeError, ValueError):
        quarter = 0

    raw_time = header_row.get("LIVE_PC_TIME") or ""
    if not isinstance(raw_time, str):
        raw_time = ""
    raw_time = raw_time.strip().upper().replace("PT", "")

    sec_remaining = 0.0
    if ":" in raw_time:
        mm, ss = raw_time.split(":", 1)
        try:
            sec_remaining = float(int(mm) * 60 + int(ss))
        except (TypeError, ValueError):
            sec_remaining = 0.0

    return quarter, sec_remaining


class NBAScoreboardClient:
    """
    Thin wrapper around nba_api ScoreboardV2 to fetch live scores.
    """

    def __init__(self, timezone: str = "America/New_York") -> None:
        self.tz = ZoneInfo(timezone)

    # -------- core fetch --------

    # src/connectors/nba/scoreboard_client.py

    def fetch_scoreboard_for_date(
        self,
        target_date: date,
    ) -> Dict[str, NBAScoreboardSnapshot]:
        ds = target_date.strftime("%m/%d/%Y")

        sb = scoreboardv2.ScoreboardV2(
            game_date=ds,
            league_id="00",
            day_offset=0,
        )
        data = sb.get_normalized_dict()

        headers = data.get("GameHeader", []) or []
        lines = data.get("LineScore", []) or []

        # (GAME_ID, TEAM_ID) -> line row (where TEAM_ABBREVIATION lives)
        line_index: Dict[tuple[str, int], Dict[str, object]] = {}
        for row in lines:
            gid = row.get("GAME_ID")
            tid = row.get("TEAM_ID")
            if not gid or tid is None:
                continue
            try:
                line_index[(str(gid), int(tid))] = row
            except (TypeError, ValueError):
                continue

        now = datetime.now(self.tz)
        out: Dict[str, NBAScoreboardSnapshot] = {}

        for h in headers:
            gid = h.get("GAME_ID")
            if not gid:
                continue
            gid = str(gid)

            home_id = h.get("HOME_TEAM_ID")
            away_id = h.get("VISITOR_TEAM_ID")

            home_id_int = None
            away_id_int = None

            try:
                home_id_int = int(home_id) if home_id is not None else None
                away_id_int = int(away_id) if away_id is not None else None
            except (TypeError, ValueError):
                pass  # keep as None

            # Look up abbreviations from LineScore
            home_line = (
                line_index.get((gid, home_id_int), {}) if home_id_int else {}
            )
            away_line = (
                line_index.get((gid, away_id_int), {}) if away_id_int else {}
            )

            def _pts(row: Dict[str, object]) -> int:
                try:
                    return int(row.get("PTS") or 0)
                except (TypeError, ValueError):
                    return 0

            score_home = _pts(home_line)
            score_away = _pts(away_line)

            # --- 🟢 FIX STARTS HERE ---
            # Try to get abbreviation from LineScore first
            home_abbrev = (home_line.get("TEAM_ABBREVIATION")
                           or "").strip().upper()
            away_abbrev = (away_line.get("TEAM_ABBREVIATION")
                           or "").strip().upper()

            # Fallback: If LineScore was empty (common for future games),
            # look up the ID in the static NBA teams list.
            if not home_abbrev and home_id_int:
                t_info = teams.find_team_name_by_id(home_id_int)
                if t_info:
                    home_abbrev = t_info.get("abbreviation", "")

            if not away_abbrev and away_id_int:
                t_info = teams.find_team_name_by_id(away_id_int)
                if t_info:
                    away_abbrev = t_info.get("abbreviation", "")
            # --- 🔴 FIX ENDS HERE ---

            status_text = (h.get("GAME_STATUS_TEXT") or "").strip()
            status_id = int(h.get("GAME_STATUS_ID") or 0)

            quarter, sec_remaining = _parse_live_clock(h)

            if status_id == 3:  # final
                if quarter <= 0:
                    quarter = 4
                sec_remaining = 0.0

            snap = NBAScoreboardSnapshot(
                game_id=gid,
                home_team=home_abbrev,
                away_team=away_abbrev,
                score_home=score_home,
                score_away=score_away,
                quarter=quarter,
                time_remaining_minutes=sec_remaining / 60.0,
                time_remaining_quarter_seconds=sec_remaining,
                status=status_text,
                timestamp=now,
                extra={},
            )
            out[gid] = snap

        return out

    # -------- polling helpers --------

    async def poll_game(
        self,
        game_id: str,
        *,
        poll_interval: float = 0.5,
        stop_on_final: bool = True,
        target_date: Optional[date] = None,  # 👈 NEW ARGUMENT
    ) -> AsyncIterator[NBAScoreboardSnapshot]:
        game_id = str(game_id)
        loop = asyncio.get_running_loop()

        while True:
            # 🟢 FIX: Use target_date if provided, else default to today
            if target_date:
                fetch_date = target_date
            else:
                fetch_date = datetime.now(self.tz).date()

            snaps = await loop.run_in_executor(
                None, self.fetch_scoreboard_for_date, fetch_date
            )
            snap = snaps.get(game_id)

            if snap:
                yield snap
                if stop_on_final and snap.status.upper().startswith("FINAL"):
                    return

            # Optional: Log warning if we can't find the game (helps debugging)
            # else:
            #     print(f"Warning: Game {game_id} not found on scoreboard for {fetch_date}")

            await asyncio.sleep(poll_interval)
