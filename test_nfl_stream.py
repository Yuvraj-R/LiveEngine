from src.connectors.nfl.scoreboard_client import NFLScoreboardClient
import asyncio
import sys
import os
from datetime import datetime

# Ensure we can import from src
sys.path.append(os.getcwd())


GAME_ID = "401772822"  # The game ID you requested


async def main():
    client = NFLScoreboardClient()

    print(f"--- Connecting to NFL Stream for Game {GAME_ID} ---")
    print("Press Ctrl+C to stop.")

    try:
        # poll_interval set to 1.0s as requested
        async for snap in client.poll_game(GAME_ID, poll_interval=1.0, stop_on_final=False):

            # Clear output for a dashboard view, or remove this line to see history scrolling
            # os.system('cls' if os.name == 'nt' else 'clear')

            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Update Received")
            print("=" * 40)
            print(f"Matchup:   {snap.away_team} vs {snap.home_team}")
            print(f"Score:     {snap.score_away} - {snap.score_home}")
            print(
                f"Clock:     Q{snap.quarter} | {int(snap.time_remaining_minutes)}m {int(snap.time_remaining_quarter_seconds % 60)}s")
            print(f"Status:    {snap.status}")
            print("-" * 40)
            print(f"Possession: {snap.possession_team}")
            print(
                f"Situation:  {snap.down} & {snap.distance} at {snap.yardline}")
            # Truncate long descriptions
            print(f"Last Play:  {snap.last_play[:100]}...")
            print("=" * 40)

    except KeyboardInterrupt:
        print("\nStopping stream...")
    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
