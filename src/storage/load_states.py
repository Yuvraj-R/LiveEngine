# src/storage/load_states.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Define Paths
NBA_DIR = PROJECT_ROOT / "src" / "storage" / "kalshi" / "merged" / "states"
NFL_DIR = PROJECT_ROOT / "src" / "storage" / "kalshi" / "merged" / "nfl_states"

log = logging.getLogger(__name__)


def load_states_for_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Load merged state files based on the config.

    Args:
        config: Dict containing:
            - "sport" (str): "nba" or "nfl" (defaults to "nba")
            - "game_ids" (List[str], optional): Specific games to load. 
                                              If empty/omitted, loads ALL games in dir.
    """
    # 1. Select Directory
    sport = config.get("sport", "nba").lower()

    if sport == "nfl":
        base_dir = NFL_DIR
    else:
        base_dir = NBA_DIR

    if not base_dir.exists():
        log.warning(f"Data directory not found for {sport}: {base_dir}")
        return []

    # 2. Identify Target Files
    target_files = []
    explicit_ids = config.get("game_ids", [])

    if explicit_ids:
        # Specific games requested
        for gid in explicit_ids:
            target_files.append(base_dir / f"{gid}.json")
    else:
        # Load ALL games in directory
        target_files = sorted(list(base_dir.glob("*.json")))
        log.info(
            f"[{sport.upper()}] Auto-discovered {len(target_files)} game files.")

    # 3. Read and Aggregate
    all_states = []

    for path in target_files:
        if not path.exists():
            log.warning(f"Skipping missing file: {path}")
            continue

        try:
            with open(path, "r") as f:
                game_states = json.load(f)

                if not game_states:
                    continue

                # Ensure states are sorted chronologically within the game file
                game_states.sort(key=lambda x: x.get("timestamp", ""))
                all_states.extend(game_states)

        except Exception as e:
            log.error(f"Error loading {path.name}: {e}")

    # 4. Global Sort
    # Sort all states by timestamp to ensure correct chronological playback across multiple games
    all_states.sort(key=lambda x: x.get("timestamp", ""))

    log.info(f"[{sport.upper()}] Loaded {len(all_states)} total state snapshots.")
    return all_states
