# src/storage/load_states.py

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List


# Assume LiveEngine and PredictEngine are siblings:
#   /home/.../LiveEngine
#   /home/.../PredictEngine
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREDICTENGINE_ROOT = PROJECT_ROOT.parent / "PredictEngine"

# Make PredictEngine/src importable as top-level (so `data...` works)
PE_SRC = PREDICTENGINE_ROOT / "src"
if PE_SRC.exists():
    sys.path.insert(0, str(PE_SRC))

try:
    # This is your existing loader in PredictEngine
    from data.kalshi.merged.load_states import (  # type: ignore
        load_states_for_config as _pe_load_states_for_config,
    )
except ImportError as e:
    raise RuntimeError(
        "Could not import PredictEngine's load_states_for_config. "
        "Check that PredictEngine/src is present next to LiveEngine."
    ) from e


def load_states_for_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Thin bridge that delegates to PredictEngine's loader for now.

    Later, we can swap this out to read game states produced directly
    by LiveEngine (e.g. data/live_states/...).
    """
    return _pe_load_states_for_config(config)
