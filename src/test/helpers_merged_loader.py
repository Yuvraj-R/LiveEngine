# src/test/helpers_merged_loader.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

DATA_DIR = Path(__file__).resolve().parent / "data" / "merged_states"


def load_merged_states(game_id: str) -> List[Dict[str, Any]]:
    """
    Load merged state list from:
      src/test/data/merged_states/<GAME_ID>.json
    """
    path = DATA_DIR / f"{game_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"merged states file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(
            f"merged states file must be a list of states: {path}")

    # assume already time-sorted as produced by PredictEngine
    return data
