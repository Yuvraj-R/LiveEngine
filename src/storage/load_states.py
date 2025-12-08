# src/storage/load_states.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Directory Mappings
DATA_DIRS = {
    "nba": PROJECT_ROOT / "src" / "storage" / "kalshi" / "merged" / "states",
    "nfl": PROJECT_ROOT / "src" / "storage" / "kalshi" / "merged" / "nfl_states",
}

log = logging.getLogger(__name__)


def load_states_for_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Load merged state files based on the config.
    """
    sport = config.get("sport", "nba").lower()
    base_dir = DATA_DIRS.get(sport)

    if not base_dir:
        raise ValueError(f"Unknown sport for backtesting: {sport}")

    if not base_dir.exists():
        log.warning(f"Data directory not found for {sport}: {base_dir}")
        return []

    # 1. Determine which files to load
    target_files = []

    explicit_ids = config.get("game_ids", [])
    if explicit_ids:
        for gid in explicit_ids:
            target_files.append(base_dir / f"{gid}.json")
    else:
        target_files = sorted(list(base_dir.glob("*.json")))
        log.info(
            f"Auto-discovered {len(target_files)} state files for {sport}")

    # 2. Load and Aggregate
    all_states = []

    for path in target_files:
        if not path.exists():
            continue

        try:
            with open(path, "r") as f:
                game_states = json.load(f)

                if not game_states:
                    continue

                # Sort WITHIN the game chronologically
                game_states.sort(key=lambda x: x.get("timestamp", ""))

                all_states.extend(game_states)

        except Exception as e:
            log.error(f"Failed to load {path}: {e}")

    # 3. CRITICAL FIX: Sort by Game ID first, then Time
    # This prevents interleaving games, which breaks the "auto_settle" logic
    # in the backtester loop.
    all_states.sort(key=lambda x: (
        x.get("game_id", ""), x.get("timestamp", "")))

    return all_states
