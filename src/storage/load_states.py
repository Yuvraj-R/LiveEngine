# src/storage/load_states.py

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)

# Directory where merged game-state JSONs live:
#   LiveEngine/src/storage/kalshi/merged/states/0022500303.json, etc.
STATES_DIR = Path(__file__).resolve().parent / "kalshi" / "merged" / "states"


def _discover_all_game_ids() -> List[str]:
    if not STATES_DIR.exists():
        raise RuntimeError(
            f"States directory not found: {STATES_DIR}. "
            "Make sure you copied merged state files into "
            "src/storage/kalshi/merged/states/."
        )

    game_ids: List[str] = []
    for path in STATES_DIR.glob("*.json"):
        game_ids.append(path.stem)

    game_ids.sort()
    return game_ids


def _load_states_for_game(game_id: str) -> List[Dict[str, Any]]:
    path = STATES_DIR / f"{game_id}.json"
    if not path.exists():
        log.warning("No states file for game_id=%s at %s", game_id, path)
        return []

    with path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Failed to parse {path}: {e}") from e

    if not isinstance(data, list):
        raise RuntimeError(
            f"Expected list of states in {path}, got {type(data)}")

    # Assume file already sorted by timestamp; just return as-is
    return data  # type: ignore[return-value]


def load_states_for_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Load merged Kalshi+NBA states for a backtest.

    Supported config keys (same shape as old PredictEngine loader):

      - "game_ids": List[str]  -> load exactly these game_ids, in order
      - "game_id": str         -> shorthand for a single game
      - otherwise              -> load *all* games found under STATES_DIR

    Returns a flat list of state dicts, grouped by game:
      [ all states for game A..., all states for game B..., ... ]
    """
    # 1) Resolve which games to load
    game_ids: List[str]

    cfg_game_ids = config.get("game_ids")
    if isinstance(cfg_game_ids, list) and cfg_game_ids:
        game_ids = [str(g) for g in cfg_game_ids]
    elif "game_id" in config and config["game_id"]:
        game_ids = [str(config["game_id"])]
    else:
        game_ids = _discover_all_game_ids()

    # Optional: respect a "max_games" limiter if present
    max_games = config.get("max_games")
    if isinstance(max_games, int) and max_games > 0:
        game_ids = game_ids[:max_games]

    # 2) Load states game-by-game, preserving contiguous blocks per game
    all_states: List[Dict[str, Any]] = []
    for gid in game_ids:
        states = _load_states_for_game(gid)
        if not states:
            continue

        # Sanity: ensure each state has game_id set (if missing, inject)
        for s in states:
            s.setdefault("game_id", gid)
        all_states.extend(states)

    return all_states
