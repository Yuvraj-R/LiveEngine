import requests
import json

# The specific game ID you mentioned (MIA vs NYJ)
GAME_ID = "401772790" 
URL = f"http://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={GAME_ID}"

def check_live_structure():
    print(f"Fetching raw data from: {URL}")
    try:
        resp = requests.get(URL, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
        }, timeout=5)
        data = resp.json()
        
        print("\n--- HEADER STATUS ---")
        header = data.get("header", {})
        status = header.get("competitions", [{}])[0].get("status", {})
        print(json.dumps(status, indent=2))

        print("\n--- SITUATION / DRIVES ---")
        # Check standard spot
        if "situation" in data:
            print("FOUND 'situation' key at root:")
            print(json.dumps(data["situation"], indent=2))
        else:
            print("MISSING 'situation' key at root.")
            
        # Check drives as backup
        drives = data.get("drives", {})
        current = drives.get("current", {})
        print("\n--- DRIVES.CURRENT ---")
        print(json.dumps(current, indent=2))

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_live_structure()