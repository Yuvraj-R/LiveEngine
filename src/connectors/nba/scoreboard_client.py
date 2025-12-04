# src/connectors/nba/scoreboard_client.py

from __future__ import annotations

import asyncio
import requests
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Optional, AsyncIterator, Any

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


class NBAScoreboardClient:
    """
    Hybrid Client:
    1. Uses nba_api ScoreboardV2 for daily scheduling/discovery (slow, comprehensive).
    2. Uses NBA CDN Boxscore for live game polling (fast, real-time).
    """

    def __init__(self, timezone: str = "America/New_York") -> None:
        self.tz = ZoneInfo(timezone)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
            "Referer": "https://www.nba.com/",
            "Origin": "https://www.nba.com"
        })

    # -------------------------------------------------------------------------
    # 1. DISCOVERY (Slow, use for finding games)
    # -------------------------------------------------------------------------

    def fetch_scoreboard_for_date(
        self,
        target_date: date,
    ) -> Dict[str, NBAScoreboardSnapshot]:
        ds = target_date.strftime("%m/%d/%Y")

        # We wrap the API call to catch timeouts/errors gracefully
        try:
            sb = scoreboardv2.ScoreboardV2(
                game_date=ds,
                league_id="00",
                day_offset=0,
                timeout=10
            )
            data = sb.get_normalized_dict()
        except Exception as e:
            print(f"[NBAScoreboardClient] Discovery Error: {e}")
            return {}

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

            home_id_int = int(home_id) if home_id else None
            away_id_int = int(away_id) if away_id else None

            # Team Abbrevs
            home_line = line_index.get(
                (gid, home_id_int), {}) if home_id_int else {}
            away_line = line_index.get(
                (gid, away_id_int), {}) if away_id_int else {}

            home_abbrev = (home_line.get("TEAM_ABBREVIATION")
                           or "").strip().upper()
            away_abbrev = (away_line.get("TEAM_ABBREVIATION")
                           or "").strip().upper()

            # Fallback for abbrevs
            if not home_abbrev and home_id_int:
                t_info = teams.find_team_name_by_id(home_id_int)
                if t_info:
                    home_abbrev = t_info.get("abbreviation", "")
            if not away_abbrev and away_id_int:
                t_info = teams.find_team_name_by_id(away_id_int)
                if t_info:
                    away_abbrev = t_info.get("abbreviation", "")

            # We don't trust ScoreboardV2 scores for live data, but we fill them here for discovery
            # so the objects aren't empty.
            try:
                s_h = int(home_line.get("PTS") or 0)
                s_a = int(away_line.get("PTS") or 0)
            except:
                s_h, s_a = 0, 0

            status_text = (h.get("GAME_STATUS_TEXT") or "").strip()

            snap = NBAScoreboardSnapshot(
                game_id=gid,
                home_team=home_abbrev,
                away_team=away_abbrev,
                score_home=s_h,
                score_away=s_a,
                quarter=0,
                time_remaining_minutes=0.0,
                time_remaining_quarter_seconds=0.0,
                status=status_text,
                timestamp=now,
                extra={},
            )
            out[gid] = snap

        return out

    # -------------------------------------------------------------------------
    # 2. LIVE POLLING (Fast, uses CDN)
    # -------------------------------------------------------------------------

    def _fetch_cdn_boxscore(self, game_id: str) -> Optional[NBAScoreboardSnapshot]:
        """
        Hit the NBA CDN for the specific game.
        URL: https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json
        """
        url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
        try:
            resp = self.session.get(url, timeout=3.0)
            if resp.status_code == 404:
                return None  # Game might not be active or ID is wrong
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            # On network blip, return None so poller just skips this tick
            return None

        game = data.get("game", {})
        if not game:
            return None

        # Parse Scores
        home = game.get("homeTeam", {})
        away = game.get("awayTeam", {})

        try:
            score_home = int(home.get("score", 0))
            score_away = int(away.get("score", 0))
        except:
            score_home, score_away = 0, 0

        # Parse Clock: Format "PT10M00.00S" or "PT02M34.00S"
        clock_str = game.get("gameClock", "")
        minutes = 0.0
        seconds = 0.0

        # Simple ISO8601 duration parser for NBA format
        # PT...M...S
        if "M" in clock_str and "S" in clock_str:
            try:
                # Remove PT
                clean = clock_str.replace("PT", "")
                parts = clean.split("M")
                minutes = float(parts[0])
                seconds_part = parts[1].replace("S", "")
                seconds = float(seconds_part)
            except:
                pass

        time_remaining_seconds = (minutes * 60) + seconds
        time_remaining_minutes = time_remaining_seconds / 60.0

        # Period
        period = int(game.get("period", 0))

        # Status
        status_text = game.get("gameStatusText", "")

        return NBAScoreboardSnapshot(
            game_id=game_id,
            home_team=home.get("teamTricode", ""),
            away_team=away.get("teamTricode", ""),
            score_home=score_home,
            score_away=score_away,
            quarter=period,
            time_remaining_minutes=time_remaining_minutes,
            time_remaining_quarter_seconds=time_remaining_seconds,
            status=status_text,
            timestamp=datetime.now(self.tz),
            extra={}
        )

    async def poll_game(
        self,
        game_id: str,
        *,
        poll_interval: float = 1.0,  # Faster polling for CDN
        stop_on_final: bool = True,
        target_date: Optional[date] = None,
    ) -> AsyncIterator[NBAScoreboardSnapshot]:

        loop = asyncio.get_running_loop()
        game_id = str(game_id)

        error_count = 0

        while True:
            # Use run_in_executor to keep the async loop unblocked while doing sync HTTP
            snap = await loop.run_in_executor(None, self._fetch_cdn_boxscore, game_id)

            if snap:
                error_count = 0
                yield snap

                # Check for Final
                # NBA CDN status is usually "Final" or "Final/OT"
                if stop_on_final and "Final" in snap.status:
                    return
            else:
                # If CDN fails (e.g. pre-game, 404, or network), back off slightly
                error_count += 1
                if error_count > 10:
                    # If we fail 10 times in a row, log it (silent here, but helps logic)
                    pass

            await asyncio.sleep(poll_interval)
