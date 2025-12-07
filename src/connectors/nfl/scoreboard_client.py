# src/connectors/nfl/scoreboard_client.py

from __future__ import annotations

import asyncio
import logging
import requests
from datetime import datetime, date
from typing import Dict, Any, Optional, AsyncIterator, List

from zoneinfo import ZoneInfo
from src.core.nfl_models import NFLScoreboardSnapshot

log = logging.getLogger(__name__)

BASE_URL = "http://site.api.espn.com/apis/site/v2/sports/football/nfl"


class NFLScoreboardClient:
    def __init__(self, timezone: str = "America/New_York") -> None:
        self.tz = ZoneInfo(timezone)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
        })

    def fetch_schedule(self, target_date: date) -> List[Dict[str, Any]]:
        date_str = target_date.strftime("%Y%m%d")
        url = f"{BASE_URL}/scoreboard?dates={date_str}"
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        games_out = []
        for evt in data.get("events", []):
            try:
                game_id = evt.get("id")
                comps = evt.get("competitions", [])[0].get("competitors", [])
                home = next(
                    (c for c in comps if c.get("homeAway") == "home"), {})
                away = next(
                    (c for c in comps if c.get("homeAway") == "away"), {})
                if game_id and home and away:
                    games_out.append({
                        "game_id": str(game_id),
                        "home_team": home.get("team", {}).get("abbreviation", "").upper(),
                        "away_team": away.get("team", {}).get("abbreviation", "").upper(),
                        "status": evt.get("status", {}).get("type", {}).get("state"),
                        "tipoff_utc": evt.get("date")
                    })
            except:
                continue
        return games_out

    # -------------------------------------------------------------------------
    # 2. LIVE POLLING (Game Summary)
    # -------------------------------------------------------------------------

    def _fetch_live_summary(self, game_id: str) -> Optional[NFLScoreboardSnapshot]:
        url = f"{BASE_URL}/summary?event={game_id}"
        try:
            resp = self.session.get(url, timeout=4.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None

        # 1. Access the main Competition object
        header = data.get("header", {})
        competitions = header.get("competitions", [])
        if not competitions:
            return None
        # <--- CRITICAL FIX: Scope to competition
        competition = competitions[0]

        # 2. Teams & Scores
        comps = competition.get("competitors", [])
        home_comp = next((c for c in comps if c.get("homeAway") == "home"), {})
        away_comp = next((c for c in comps if c.get("homeAway") == "away"), {})

        home_team = home_comp.get("team", {}).get("abbreviation", "UNK")
        away_team = away_comp.get("team", {}).get("abbreviation", "UNK")

        def parse_score(val):
            try:
                return int(val)
            except:
                return 0

        score_home = parse_score(home_comp.get("score"))
        score_away = parse_score(away_comp.get("score"))

        # 3. Clock & Status (Now pulling from competition['status'])
        status_data = competition.get("status", {})
        status_text = status_data.get("type", {}).get("detail", "")
        quarter = status_data.get("period", 0)
        display_clock = status_data.get("displayClock", "0:00")

        minutes, seconds = 0.0, 0.0
        if ":" in display_clock:
            parts = display_clock.split(":")
            try:
                minutes = float(parts[0])
                seconds = float(parts[1])
            except:
                pass

        time_rem_sec = (minutes * 60) + seconds

        # 4. Situation Extraction
        possession_team = None
        down = 0
        distance = 0
        yardline = 0
        last_play_text = ""

        # Root Situation
        sit = data.get("situation", {})

        # Drive Fallback
        if not sit:
            drives = data.get("drives", {})
            current_drive = drives.get("current", {})
            if current_drive:
                plays = current_drive.get("plays", [])
                if plays:
                    last_play_obj = plays[-1]
                    last_play_text = last_play_obj.get("text", "")
                    end_state = last_play_obj.get("end", {})

                    down = end_state.get("down", 0)
                    distance = end_state.get("distance", 0)
                    yardline = end_state.get("yardLine", 0)

                    poss_id = last_play_obj.get("start", {}).get("team", {}).get("id") or \
                        current_drive.get("team", {}).get("id")

                    if poss_id:
                        if str(poss_id) == str(home_comp.get("id")):
                            possession_team = home_team
                        elif str(poss_id) == str(away_comp.get("id")):
                            possession_team = away_team
        else:
            down = int(sit.get("down", 0))
            distance = int(sit.get("distance", 0))
            yardline = int(sit.get("yardLine", 0))
            last_play_text = sit.get("lastPlay", {}).get("text", "")

            poss_id = sit.get("possession")
            if poss_id:
                if str(poss_id) == str(home_comp.get("id")):
                    possession_team = home_team
                elif str(poss_id) == str(away_comp.get("id")):
                    possession_team = away_team

        return NFLScoreboardSnapshot(
            game_id=str(game_id),
            home_team=home_team,
            away_team=away_team,
            score_home=score_home,
            score_away=score_away,
            quarter=quarter,
            time_remaining_minutes=time_rem_sec / 60.0,
            time_remaining_quarter_seconds=time_rem_sec,
            possession_team=possession_team,
            down=down,
            distance=distance,
            yardline=yardline,
            status=status_text,
            timestamp=datetime.now(self.tz),
            last_play=last_play_text,
            extra={}
        )

    async def poll_game(self, game_id: str, *, poll_interval: float = 1.0, stop_on_final: bool = True) -> AsyncIterator[NFLScoreboardSnapshot]:
        loop = asyncio.get_running_loop()
        while True:
            snap = await loop.run_in_executor(None, self._fetch_live_summary, game_id)
            if snap:
                yield snap
                if stop_on_final and "Final" in snap.status:
                    return
            await asyncio.sleep(poll_interval)
