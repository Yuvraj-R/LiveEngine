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

# ESPN Hidden API Endpoints
# "site.api" is more reliable than "cdn" for specific event summaries in NFL
BASE_URL = "http://site.api.espn.com/apis/site/v2/sports/football/nfl"


class NFLScoreboardClient:
    def __init__(self, timezone: str = "America/New_York") -> None:
        self.tz = ZoneInfo(timezone)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
        })

    # -------------------------------------------------------------------------
    # 1. DISCOVERY (Schedule)
    # -------------------------------------------------------------------------

    def fetch_schedule(self, target_date: date) -> List[Dict[str, Any]]:
        """
        Fetch all games for a specific date to generate Jobs.
        Returns a list of simplified dicts: {game_id, home, away, status, tipoff_utc}
        """
        # ESPN uses YYYYMMDD format
        date_str = target_date.strftime("%Y%m%d")
        url = f"{BASE_URL}/scoreboard?dates={date_str}"

        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"ESPN Schedule fetch failed: {e}")
            return []

        games_out = []
        events = data.get("events", [])

        for evt in events:
            try:
                game_id = evt.get("id")
                # Status: "pre", "in", "post"
                status_state = evt.get("status", {}).get(
                    "type", {}).get("state")

                # Competitors
                comps = evt.get("competitions", [])[0].get("competitors", [])
                home_comp = next(
                    (c for c in comps if c.get("homeAway") == "home"), {})
                away_comp = next(
                    (c for c in comps if c.get("homeAway") == "away"), {})

                home_team = home_comp.get("team", {}).get("abbreviation")
                away_team = away_comp.get("team", {}).get("abbreviation")

                # Tipoff Time (ISO string from ESPN, usually UTC with Z)
                date_utc = evt.get("date")

                if game_id and home_team and away_team:
                    games_out.append({
                        "game_id": str(game_id),
                        "home_team": home_team.upper(),
                        "away_team": away_team.upper(),
                        "status": status_state,
                        "tipoff_utc": date_utc
                    })
            except Exception:
                continue

        return games_out

    # -------------------------------------------------------------------------
    # 2. LIVE POLLING (Game Summary)
    # -------------------------------------------------------------------------

    def _fetch_live_summary(self, game_id: str) -> Optional[NFLScoreboardSnapshot]:
        """
        Fetch highly detailed live state (Down, Distance, Yardline) from ESPN.
        """
        url = f"{BASE_URL}/summary?event={game_id}"

        try:
            resp = self.session.get(url, timeout=4.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            # Silent fail on network blip
            return None

        # 1. Basic Scoreboard
        # ESPN API structure: header -> competitions -> competitors
        header = data.get("header", {})
        comps = header.get("competitions", [])[0].get("competitors", [])

        home_comp = next((c for c in comps if c.get("homeAway") == "home"), {})
        away_comp = next((c for c in comps if c.get("homeAway") == "away"), {})

        home_team = home_comp.get("team", {}).get("abbreviation", "UNK")
        away_team = away_comp.get("team", {}).get("abbreviation", "UNK")

        try:
            score_home = int(home_comp.get("score", 0))
            score_away = int(away_comp.get("score", 0))
        except:
            score_home, score_away = 0, 0

        # 2. Clock & Status
        status_data = header.get("status", {})
        status_text = status_data.get("type", {}).get(
            "detail", "")  # e.g. "3rd Quarter" or "Final"
        quarter = status_data.get("period", 0)
        display_clock = status_data.get("displayClock", "0:00")  # "14:30"

        # Parse Clock "MM:SS" -> seconds
        minutes = 0.0
        seconds = 0.0
        if ":" in display_clock:
            try:
                parts = display_clock.split(":")
                minutes = float(parts[0])
                seconds = float(parts[1])
            except:
                pass

        time_rem_q_sec = (minutes * 60) + seconds
        time_rem_min = time_rem_q_sec / 60.0

        # 3. Situation (Down, Dist, Possession)
        # Situation block is sometimes directly in drives -> current, or at root?
        # In `summary` endpoint, it's usually inside `drives` -> `current`
        # OR sometimes under `situation` key if game is live.

        # We prefer the top-level 'situation' if available, otherwise look at current drive.
        sit = data.get("situation", {})
        if not sit:
            # Fallback to current drive logic if needed, but 'situation' is standard for live games.
            pass

        # Possession: ESPN gives a Team ID. We must map it to Home/Away.
        poss_id = sit.get("possession")
        possession_team = None

        if poss_id:
            # Compare strings to be safe
            if str(poss_id) == str(home_comp.get("id")):
                possession_team = home_team
            elif str(poss_id) == str(away_comp.get("id")):
                possession_team = away_team

        down = int(sit.get("down", 0))
        distance = int(sit.get("distance", 0))

        # Yardline: ESPN usually provides `yardLine` (0-100).
        # Sometimes it's `possessionText` like "KC 25".
        # We'll take the raw integer if present.
        yardline = int(sit.get("yardLine", 0))

        last_play = sit.get("lastPlay", {}).get("text", "")

        # Timestamp
        now = datetime.now(self.tz)

        return NFLScoreboardSnapshot(
            game_id=str(game_id),
            home_team=home_team,
            away_team=away_team,
            score_home=score_home,
            score_away=score_away,
            quarter=quarter,
            time_remaining_minutes=time_rem_min,
            time_remaining_quarter_seconds=time_rem_q_sec,
            possession_team=possession_team,
            down=down,
            distance=distance,
            yardline=yardline,
            status=status_text,
            timestamp=now,
            last_play=last_play,
            extra={}
        )

    async def poll_game(
        self,
        game_id: str,
        *,
        poll_interval: float = 2.0,
        stop_on_final: bool = True
    ) -> AsyncIterator[NFLScoreboardSnapshot]:

        loop = asyncio.get_running_loop()

        while True:
            # Run sync request in thread
            snap = await loop.run_in_executor(None, self._fetch_live_summary, game_id)

            if snap:
                yield snap
                if stop_on_final and "Final" in snap.status:
                    return

            await asyncio.sleep(poll_interval)
