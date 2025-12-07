import requests
import time
import os
from datetime import datetime

# --- CONFIGURATION ---
GAME_ID = "0022500355"  # Provided ID for tonight's game
URL = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{GAME_ID}.json"


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def get_nba_data():
    try:
        # NBA CDN requires a User-Agent or it might block you
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
            "Referer": "https://www.nba.com/"
        }
        r = requests.get(URL, headers=headers, timeout=2)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        return None


while True:
    data = get_nba_data()
    clear_screen()

    print(f"--- NBA OFFICIAL CDN: {GAME_ID} ---")
    print(f"Local Time: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    print("-" * 34)

    if data and 'game' in data:
        game = data['game']

        # 1. Game Status
        status = game.get('gameStatusText', 'Unknown')

        # 2. Teams & Scores
        home = game.get('homeTeam', {})
        away = game.get('awayTeam', {})

        h_team = home.get('teamTricode', 'HOM')
        a_team = away.get('teamTricode', 'AWY')
        h_score = home.get('score', 0)
        a_score = away.get('score', 0)

        # 3. Official Clock (The most important metric)
        # Note: Sometimes clock is in 'gameStatusText', sometimes in 'period' logic
        # We rely on the status text for simplicity as it usually says "Q1 10:45"

        print(f" {a_team:<3}  vs  {h_team:>3}")
        print(f" {a_score:<3}   -   {h_score:>3}")
        print("-" * 34)
        print(f"STATUS: {status}")

        # Last updated timestamp from the JSON itself (if available)
        # useful to see how 'stale' the file is
        timestamp = data.get('meta', {}).get('time', 'N/A')
        print(f"Feed Time: {timestamp}")

    else:
        print("Connecting to NBA CDN...")
        print("(If this persists, the Game ID might be invalid or pre-game)")

    # NBA CDN updates roughly every 1-3 seconds.
    # Polling faster than 1s is useless as the file is cached.
    time.sleep(1)
