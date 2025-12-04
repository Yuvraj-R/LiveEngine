import requests
import json
from datetime import datetime

# MIA @ DAL (from your log)
GAME_ID = "0022500332" 

def test_cdn_boxscore():
    # This is the "Live Boxscore" endpoint. It is extremely fast.
    url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{GAME_ID}.json"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com"
    }

    print(f"Fetching: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        
        game = data.get("game", {})
        
        # 1. Scores
        home = game.get("homeTeam", {})
        away = game.get("awayTeam", {})
        
        print(f"\n--- LIVE DATA CHECK ---")
        print(f"Game Status: {game.get('gameStatusText')}")
        print(f"Clock:       {game.get('gameClock')}")
        print(f"Period:      {game.get('period')}")
        print(f"Matchup:     {away.get('teamTricode')} @ {home.get('teamTricode')}")
        print(f"Score:       {away.get('score')} - {home.get('score')}")
        print(f"-----------------------\n")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_cdn_boxscore()