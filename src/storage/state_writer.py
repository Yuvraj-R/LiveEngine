# src/storage/state_writer.py

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

# Path definitions
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATES_DIR = PROJECT_ROOT / "src" / "storage" / "kalshi" / "merged" / "states"


class PredictEngineStateWriter:
    """
    Accumulates merged NBA+Kalshi states for a single game and writes them
    to: src/storage/kalshi/merged/states/<GAME_ID>.json

    Format: A valid JSON array of state dicts, but formatted with newlines 
    for readability:
    [
    {...},
    {...}
    ]

    NOTE: Writes to disk immediately on append_state to prevent data loss.
    """

    def __init__(self, game_id: str) -> None:
        self.game_id = game_id
        self.path = STATES_DIR / f"{game_id}.json"
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
        # Serialize with no indent (compact object) but we will add newlines around it
        new_entry_str = json.dumps(state)
        new_entry_bytes = new_entry_str.encode("utf-8")

        # Open in binary read/write mode
        with self.path.open("rb+") as f:
            f.seek(0, 2)  # Go to end of file
            file_len = f.tell()

            # Logic to handle the trailing ']' or '\n]'
            if file_len <= 2:
                # File is likely "[]". Overwrite the closing bracket.
                # Result: [\n{...}\n]
                f.seek(-1, 2)
                f.write(b"\n" + new_entry_bytes + b"\n]")
            else:
                # File likely ends in "\n]".
                # We backtrack to overwrite the "]" but keep the "\n" if we want,
                # or strictly manage the commas.

                # Scan backwards to find the last ']'
                # Usually it's the last byte or the last non-whitespace byte.
                # A safe bet for our format is to seek back past the \n]

                # Check last 2 bytes
                f.seek(-2, 2)
                tail = f.read(2)

                if tail == b"\n]":
                    # Overwrite the "\n]"
                    f.seek(-2, 2)
                    # Add: ,\n{...}\n]
                    f.write(b",\n" + new_entry_bytes + b"\n]")
                elif tail.endswith(b"]"):
                    # Just ends in "]" (maybe edited manually?)
                    f.seek(-1, 2)
                    f.write(b",\n" + new_entry_bytes + b"\n]")
                else:
                    # Fallback: Just append (this might result in invalid json if file is corrupt)
                    f.write(b",\n" + new_entry_bytes + b"\n]")

        self._count += 1

    def flush(self) -> None:
        """
        No-op: Data is written immediately in append_state.
        """
        pass
