# src/connectors/nba/scoreboard_client.py

from __future__ import annotations

import asyncio
import requests
import traceback
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Optional, AsyncIterator, Any

from zoneinfo import ZoneInfo
from nba_api.stats.endpoints import scoreboardv2
from nba_api.stats.static import teams

from src.core.nba_models import NBAScoreboardSnapshot


class NBAScoreboardError(RuntimeError):
    pass


class NBAScoreboardClient:
    def __init__(self, timezone: str = "America/New_York") -> None:
        self.tz = ZoneInfo(timezone)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
            "Referer": "https://www.nba.com/",
            "Origin": "https://www.nba.com"
        })

    # 1. DISCOVERY
    def fetch_scoreboard_for_date(self, target_date: date) -> Dict[str, NBAScoreboardSnapshot]:
        ds = target_date.strftime("%m/%d/%Y")

        # We allow this to crash if it fails so we see it in logs
        sb = scoreboardv2.ScoreboardV2(
            game_date=ds, league_id="00", day_offset=0, timeout=10)
        data = sb.get_normalized_dict()

        headers = data.get("GameHeader", []) or []
        lines = data.get("LineScore", []) or []

        line_index = {}
        for row in lines:
            if row.get("GAME_ID") and row.get("TEAM_ID"):
                line_index[(str(row["GAME_ID"]), int(row["TEAM_ID"]))] = row

        now = datetime.now(self.tz)
        out = {}

        for h in headers:
            gid = str(h.get("GAME_ID"))
            home_id = int(h.get("HOME_TEAM_ID") or 0)
            away_id = int(h.get("VISITOR_TEAM_ID") or 0)

            home_line = line_index.get((gid, home_id), {})
            away_line = line_index.get((gid, away_id), {})

            h_abbr = (home_line.get("TEAM_ABBREVIATION") or "").strip().upper()
            a_abbr = (away_line.get("TEAM_ABBREVIATION") or "").strip().upper()

            # --- FALLBACK RESTORED ---
            if not h_abbr and home_id:
                t_info = teams.find_team_name_by_id(home_id)
                if t_info:
                    h_abbr = t_info.get("abbreviation", "")

            if not a_abbr and away_id:
                t_info = teams.find_team_name_by_id(away_id)
                if t_info:
                    a_abbr = t_info.get("abbreviation", "")
            # -------------------------

            out[gid] = NBAScoreboardSnapshot(
                game_id=gid,
                home_team=h_abbr, away_team=a_abbr,
                score_home=0, score_away=0, quarter=0,
                time_remaining_minutes=0.0, time_remaining_quarter_seconds=0.0,
                status=h.get("GAME_STATUS_TEXT", ""),
                timestamp=now,
                possession_team_id=None,
                in_bonus_home=False, in_bonus_away=False,
                fouls_home=0, fouls_away=0,
                timeouts_home=0, timeouts_away=0,
                extra={}
            )
        return out

    # 2. POLLING
    def _fetch_cdn_boxscore(self, game_id: str) -> Optional[NBAScoreboardSnapshot]:
        url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
        try:
            resp = self.session.get(url, timeout=3.0)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None

        game = data.get("game", {})
        if not game:
            return None

        home = game.get("homeTeam", {})
        away = game.get("awayTeam", {})
        home_abbr = home.get("teamTricode", "")
        away_abbr = away.get("teamTricode", "")

        try:
            score_home = int(home.get("score", 0))
            score_away = int(away.get("score", 0))
        except:
            score_home, score_away = 0, 0

        clock_str = game.get("gameClock", "")
        minutes = 0.0
        seconds = 0.0
        if "M" in clock_str and "S" in clock_str:
            try:
                clean = clock_str.replace("PT", "")
                parts = clean.split("M")
                minutes = float(parts[0])
                seconds = float(parts[1].replace("S", ""))
            except:
                pass
        time_rem_sec = (minutes * 60) + seconds

        def get_stat(team_obj, key):
            if key in team_obj:
                return team_obj[key]
            stats = team_obj.get("statistics", {})
            return stats.get(key, 0)

        fouls_home = int(get_stat(home, "teamFouls") or 0)
        fouls_away = int(get_stat(away, "teamFouls") or 0)
        timeouts_home = int(home.get("timeoutsRemaining", 0))
        timeouts_away = int(away.get("timeoutsRemaining", 0))
        in_bonus_home = bool(home.get("inBonus", False))
        in_bonus_away = bool(away.get("inBonus", False))

        poss_id = str(game.get("possession", ""))
        poss_abbr = None
        if poss_id:
            if poss_id == str(home.get("teamId")):
                poss_abbr = home_abbr
            elif poss_id == str(away.get("teamId")):
                poss_abbr = away_abbr

        return NBAScoreboardSnapshot(
            game_id=game_id,
            home_team=home_abbr, away_team=away_abbr,
            score_home=score_home, score_away=score_away,
            quarter=int(game.get("period", 0)),
            time_remaining_minutes=time_rem_sec / 60.0,
            time_remaining_quarter_seconds=time_rem_sec,
            status=game.get("gameStatusText", ""),
            timestamp=datetime.now(self.tz),
            possession_team_id=poss_abbr,
            in_bonus_home=in_bonus_home, in_bonus_away=in_bonus_away,
            fouls_home=fouls_home, fouls_away=fouls_away,
            timeouts_home=timeouts_home, timeouts_away=timeouts_away,
            extra={}
        )

    async def poll_game(self, game_id: str, *, poll_interval: float = 1.0, stop_on_final: bool = True, target_date: Optional[date] = None) -> AsyncIterator[NBAScoreboardSnapshot]:
        loop = asyncio.get_running_loop()
        while True:
            snap = await loop.run_in_executor(None, self._fetch_cdn_boxscore, game_id)
            if snap:
                yield snap
                if stop_on_final and "Final" in snap.status:
                    return
            await asyncio.sleep(poll_interval)
