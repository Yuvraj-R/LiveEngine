# src/core/trade_logger.py
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_BASE_DIR = PROJECT_ROOT / "src" / "storage" / "logs" / "trades"


class TradeLogger:
    def __init__(self, sport: str, dry_run: bool):
        self.sport = sport.lower()
        self.dry_run = dry_run
        self.date_str = datetime.utcnow().strftime("%Y-%m-%d")
        self.mode = "DRY" if dry_run else "LIVE"

        # Subdirectory per sport: storage/logs/trades/nba/trades_2025-12-07.csv
        self.log_dir = LOG_BASE_DIR / self.sport
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.filepath = self.log_dir / f"trades_{self.date_str}.csv"

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

    def _extract_execution_details(self, result: Any) -> tuple[float, int]:
        price = 0.0
        contracts = 0

        if not result.raw or not isinstance(result.raw, dict):
            return 0.0, 0

        # Dry Run
        if "payload" in result.raw:
            payload = result.raw["payload"]
            cents = payload.get("price_cents", 0)
            price = cents / 100.0
            contracts = payload.get("count", 0)
            return price, contracts

        # Live Run
        data = result.raw.get("order") or result.raw

        if "yes_price" in data:
            price = data["yes_price"] / 100.0
        elif "price" in data:
            price = data["price"] / 100.0

        if "count" in data:
            contracts = data["count"]
        elif "filled_count" in data:
            contracts = data["filled_count"]

        return price, contracts

    def log_order_attempt(self, game_id: str, strategy_name: str, intent: Any, result: Any):
        now = datetime.utcnow().isoformat()
        status = "FILLED" if result.ok else "FAILED"
        if self.dry_run:
            status = "DRY_FILLED" if result.ok else "DRY_FAILED"

        size_dollars = getattr(intent, 'position_size', 0)
        action = getattr(intent, 'action', 'unknown')
        market = getattr(intent, 'market_id', 'unknown')

        price, contracts = self._extract_execution_details(result)
        if price == 0:
            price = getattr(intent, 'price', 0)

        row = [
            now, self.mode, game_id, strategy_name, market, action,
            price, size_dollars, contracts,
            result.order_id, status, result.error or ""
        ]

        try:
            with open(self.filepath, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            print(f"CRITICAL: Failed to write to trade log: {e}")
