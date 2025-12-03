import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "src" / "storage" / "logs" / "trades"


class TradeLogger:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        self.date_str = datetime.utcnow().strftime("%Y-%m-%d")
        self.mode = "DRY" if dry_run else "LIVE"

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.filepath = LOG_DIR / f"trades_{self.date_str}.csv"

        self._ensure_header()

    def _ensure_header(self):
        if not self.filepath.exists():
            with open(self.filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "mode", "game_id", "strategy",
                    "market_ticker", "action", "price",
                    "size_dollars", "contracts", "order_id", "status", "error"
                ])

    def log_order_attempt(
        self,
        game_id: str,
        strategy_name: str,
        intent: Any,
        result: Any
    ):
        """
        Logs an order result (success or fail) to CSV.
        """
        now = datetime.utcnow().isoformat()

        status = "FILLED" if result.ok else "FAILED"
        if self.dry_run:
            status = "DRY_FILLED" if result.ok else "DRY_FAILED"

        # Safe attribute access
        # Some intents might not have price limits
        price = getattr(intent, 'price', 0)
        size = getattr(intent, 'position_size', 0)
        action = getattr(intent, 'action', 'unknown')
        market = getattr(intent, 'market_id', 'unknown')

        row = [
            now,
            self.mode,
            game_id,
            strategy_name,
            market,
            action,
            price,
            size,
            0,  # Contracts (calculated later or returned by broker)
            result.order_id,
            status,
            result.error or ""
        ]

        try:
            with open(self.filepath, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            print(f"CRITICAL: Failed to write to trade log: {e}")
