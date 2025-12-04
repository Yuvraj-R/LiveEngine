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

    def _extract_execution_details(self, result: Any) -> tuple[float, int]:
        """
        Parses the Broker result to find the actual price and contracts used.
        Returns (price_float, contracts_int).
        """
        price = 0.0
        contracts = 0

        if not result.raw or not isinstance(result.raw, dict):
            return 0.0, 0

        # 1. Dry Run / Payload Inspection
        # In dry run, raw = {"dry_run": True, "payload": {...}}
        if "payload" in result.raw:
            payload = result.raw["payload"]
            cents = payload.get("price_cents", 0)
            price = cents / 100.0
            contracts = payload.get("count", 0)
            return price, contracts

        # 2. Live Run (Kalshi API Response)
        # Kalshi response usually wraps the order in "order": {...} or returns it directly
        data = result.raw.get("order") or result.raw

        # Try to find price
        # Live orders might return 'yes_price', 'no_price', or 'execution_price'
        if "yes_price" in data:
            price = data["yes_price"] / 100.0
        elif "price" in data:
            # Sometimes APIs return price in cents, sometimes ratio.
            # Safe assumption for Kalshi API v2 'price' field is usually cents.
            price = data["price"] / 100.0

        # Try to find count
        if "count" in data:
            contracts = data["count"]
        elif "filled_count" in data:
            contracts = data["filled_count"]

        return price, contracts

    def log_order_attempt(
        self,
        game_id: str,
        strategy_name: str,
        intent: Any,
        result: Any
    ):
        now = datetime.utcnow().isoformat()

        status = "FILLED" if result.ok else "FAILED"
        if self.dry_run:
            status = "DRY_FILLED" if result.ok else "DRY_FAILED"

        # 1. Get Intent Basics
        # Use getattr safely in case attributes are missing
        size_dollars = getattr(intent, 'position_size', 0)
        action = getattr(intent, 'action', 'unknown')
        market = getattr(intent, 'market_id', 'unknown')

        # 2. Get Execution Details (Price & Contracts)
        price, contracts = self._extract_execution_details(result)

        # Fallback: if result didn't have price (e.g. failed before payload built),
        # try checking if intent had a limit price
        if price == 0:
            price = getattr(intent, 'price', 0)

        row = [
            now,
            self.mode,
            game_id,
            strategy_name,
            market,
            action,
            price,         # Now correctly populated
            size_dollars,
            contracts,     # Now correctly populated
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
