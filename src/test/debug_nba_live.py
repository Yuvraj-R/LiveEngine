import requests
import json

# OKC vs UTA game ID from your log
GAME_ID = "0022500364"
URL = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{GAME_ID}.json"


def check_nba_structure():
    print(f"Fetching raw data from: {URL}")
    try:
        resp = requests.get(URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        print(data)

        game = data.get("game", {})

        print("\n--- GAME ROOT ---")
        # Check possession at root
        if "possession" in game:
            print(f"Possession Field: {game['possession']}")
        else:
            print("MISSING 'possession' at game root.")

        print("\n--- HOME TEAM STATS ---")
        home = game.get("homeTeam", {})

        # Check root fields
        print(f"Team ID: {home.get('teamId')}")
        print(f"Bonus: {home.get('inBonus')}")
        print(f"Timeouts: {home.get('timeoutsRemaining')}")

        # Check statistics object
        stats = home.get("statistics", {})
        print(f"Stats Keys: {list(stats.keys())}")
        print(f"Fouls (in stats): {stats.get('teamFouls')}")
        print(f"Fouls (at root): {home.get('fouls')}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    check_nba_structure()
