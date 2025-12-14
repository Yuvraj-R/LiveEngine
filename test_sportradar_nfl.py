import requests
import time
import sys
import os
from datetime import datetime

# ==========================================
# CONFIGURATION
# ==========================================
# 1. PASTE YOUR API KEY HERE
API_KEY = "wfd69Nxp4BUU5xgitmPJX61rkXMITvavJGRxPfah"

# 1. Run script once to see the schedule and find the UUID.
# 2. Paste the UUID below.
GAME_ID = "ca630b7f-6f47-4144-b93b-dd1e4c443e07"

# 3. POLL INTERVAL (Keep > 2s to save quota)
POLL_INTERVAL = 1.0


class SportRadarNFLProbe:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.sportradar.com/nfl/official/trial/v7/en"
        self.session = requests.Session()
        self.params = {"api_key": self.api_key}

    def poll_game_boxscore(self, game_uuid):
        url = f"{self.base_url}/games/{game_uuid}/boxscore.json"

        print(f"--- Polling SportRadar Stream for {game_uuid} ---")
        print("Press Ctrl+C to stop.")

        while True:
            start_time = time.time()
            try:
                resp = self.session.get(url, params=self.params, timeout=5)
                if resp.status_code == 429:
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] Rate Limited (429). Retrying...")
                    time.sleep(2)
                    continue
                elif resp.status_code == 403:
                    print("CRITICAL: Quota Exceeded or Invalid Key (403).")
                    break

                resp.raise_for_status()
                data = resp.json()

                self._print_espn_style(data)

            except Exception as e:
                print(f"Error: {e}")

            elapsed = time.time() - start_time
            sleep_time = max(0.1, POLL_INTERVAL - elapsed)
            time.sleep(sleep_time)

    def _print_espn_style(self, data):
        # Extract Core Data
        summary = data.get('summary', {})
        home = summary.get('home', {})
        away = summary.get('away', {})

        home_team = home.get('alias', 'UNK')
        away_team = away.get('alias', 'UNK')

        score_home = home.get('points', 0)
        score_away = away.get('points', 0)

        # --- CLOCK & STATUS FIX ---
        # SportRadar puts the live clock inside 'situation' -> 'clock' usually.
        # Fallback to root 'clock' if not found.
        situation = data.get('situation', {})
        clock_str = situation.get('clock') or data.get('clock', '00:00')
        quarter = data.get('quarter', 0)
        status_raw = data.get('status', 'Unknown')

        # Formatting Time
        time_display = clock_str
        if ":" in str(clock_str):
            try:
                m, s = clock_str.split(":")
                time_display = f"{int(m)}m {int(s)}s"
            except:
                pass

        # --- SITUATION FIX (yfd) ---
        poss_team = "UNK"
        down = 0
        distance = 0
        yardline = 0

        if situation:
            # 1. Possession
            poss_data = situation.get('possession', {})
            if isinstance(poss_data, dict):
                poss_team = poss_data.get('alias', 'UNK')
            else:
                poss_team = str(poss_data)

            # 2. Down & Distance
            down = situation.get('down', 0)
            # CRITICAL FIX: SportRadar uses 'yfd' (Yards First Down)
            distance = situation.get('yfd', 0)

            # 3. Yardline
            location = situation.get('location', {})
            yardline = location.get('yardline', 0) if location else 0

        # Last Play Retrieval
        last_play_text = "Waiting for play..."
        last_event = data.get('last_event', {})
        if last_event:
            last_play_text = last_event.get('description', '')

        if not last_play_text and situation:
            lp = situation.get('last_play', {})
            if lp:
                last_play_text = lp.get('description', '')

        # Output
        # os.system('cls' if os.name == 'nt' else 'clear')
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] SportRadar Update")
        print("=" * 40)
        print(f"Matchup:   {away_team} vs {home_team}")
        print(f"Score:     {score_away} - {score_home}")
        print(f"Clock:     Q{quarter} | {time_display}")
        print(f"Status:    {status_raw}")
        print("-" * 40)
        print(f"Possession: {poss_team}")
        print(f"Situation:  {down} & {distance} at {yardline}")
        print(f"Last Play:  {last_play_text[:100]}...")
        print("=" * 40)


if __name__ == "__main__":
    if "YOUR_" in API_KEY:
        print("CRITICAL: Set your API_KEY.")
        sys.exit(1)
    if "PASTE_" in GAME_ID:
        print("CRITICAL: Set the GAME_ID (UUID) for the specific game.")
        sys.exit(1)

    probe = SportRadarNFLProbe(API_KEY)
    probe.poll_game_boxscore(GAME_ID)
