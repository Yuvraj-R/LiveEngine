# src/connectors/nba/scoreboard_client.py

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Optional, AsyncIterator

from zoneinfo import ZoneInfo
from nba_api.stats.endpoints import scoreboardv2

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
    # Quarter
    quarter = 0
    raw_period = header_row.get("LIVE_PERIOD")
    try:
        if raw_period is not None:
            quarter = int(raw_period)
    except (TypeError, ValueError):
        quarter = 0

    # LIVE_PC_TIME is often like "11:23" or "05:42"
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

    Usage:
        client = NBAScoreboardClient()
        snaps = client.fetch_scoreboard_for_date(date.today())
        snap = snaps["0022500277"]

        async for snap in client.poll_game("0022500277", poll_interval=5.0):
            ...
    """

    def __init__(self, timezone: str = "America/New_York") -> None:
        self.tz = ZoneInfo(timezone)

    # -------- core fetch --------

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

        # (GAME_ID, TEAM_ID) -> line row
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
            try:
                home_id_int = int(home_id) if home_id is not None else None
                away_id_int = int(away_id) if away_id is not None else None
            except (TypeError, ValueError):
                continue

            home_abbrev = (
                h.get("HOME_TEAM_ABBREVIATION")
                or h.get("HOME_TEAM_ABBREV")
                or ""
            )
            away_abbrev = (
                h.get("VISITOR_TEAM_ABBREVIATION")
                or h.get("VISITOR_TEAM_ABBREV")
                or ""
            )

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

            status_text = (h.get("GAME_STATUS_TEXT") or "").strip()
            status_id = int(h.get("GAME_STATUS_ID") or 0)

            quarter, sec_remaining = _parse_live_clock(h)

            if status_id == 3:  # final
                if quarter <= 0:
                    quarter = 4
                sec_remaining = 0.0

            snap = NBAScoreboardSnapshot(
                game_id=gid,
                home_team=str(home_abbrev),
                away_team=str(away_abbrev),
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
        poll_interval: float = 5.0,
        stop_on_final: bool = True,
    ) -> AsyncIterator[NBAScoreboardSnapshot]:
        """
        Async generator yielding scoreboard snapshots for one game_id.
        """
        game_id = str(game_id)

        loop = asyncio.get_running_loop()
        while True:
            today_et = datetime.now(self.tz).date()

            # run nba_api call in threadpool to avoid blocking event loop
            snaps = await loop.run_in_executor(
                None, self.fetch_scoreboard_for_date, today_et
            )
            snap = snaps.get(game_id)

            if snap:
                yield snap

                if stop_on_final and snap.status.upper().startswith("FINAL"):
                    return

            await asyncio.sleep(poll_interval)
