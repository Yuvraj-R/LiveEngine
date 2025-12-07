# src/storage/state_writer.py

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

# Path definitions
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Default NBA directory (Preserve behavior)
DEFAULT_STATES_DIR = PROJECT_ROOT / "src" / \
    "storage" / "kalshi" / "merged" / "states"


class PredictEngineStateWriter:
    """
    Accumulates merged states for a single game and writes them to disk.
    Append-only for safety.
    """

    def __init__(self, game_id: str, output_dir: Path = None) -> None:
        self.game_id = game_id

        # Use provided dir or default to NBA
        target_dir = output_dir if output_dir else DEFAULT_STATES_DIR
        self.path = target_dir / f"{game_id}.json"

        self._count = 0

        # Ensure directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize file if it doesn't exist
        if not self.path.exists():
            with self.path.open("w", encoding="utf-8") as f:
                f.write("[]")

    @property
    def count(self) -> int:
        return self._count

    def append_state(self, state: Dict[str, Any]) -> None:
        """
        Immediately writes the state to the file, maintaining a multi-line JSON array.
        """
        new_entry_str = json.dumps(state)
        new_entry_bytes = new_entry_str.encode("utf-8")

        with self.path.open("rb+") as f:
            f.seek(0, 2)  # Go to end
            file_len = f.tell()

            if file_len <= 2:
                # File is "[]" -> "[\n{...}\n]"
                f.seek(-1, 2)
                f.write(b"\n" + new_entry_bytes + b"\n]")
            else:
                # File is "...]" -> "...,\n{...}\n]"
                # Check for existing newline setup
                f.seek(-2, 2)
                tail = f.read(2)

                if tail == b"\n]":
                    f.seek(-2, 2)
                    f.write(b",\n" + new_entry_bytes + b"\n]")
                elif tail.endswith(b"]"):
                    f.seek(-1, 2)
                    f.write(b",\n" + new_entry_bytes + b"\n]")
                else:
                    # Fallback append
                    f.write(b",\n" + new_entry_bytes + b"\n]")

        self._count += 1

    def flush(self) -> None:
        pass
