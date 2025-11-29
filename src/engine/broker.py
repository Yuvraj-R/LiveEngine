# src/engine/broker.py

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.strategies.strategy import TradeIntent


def _find_market_in_state(state: Dict[str, Any], market_id: str) -> Optional[Dict[str, Any]]:
    markets = state.get("markets") or []
    for m in markets:
        if isinstance(m, dict) and m.get("market_id") == market_id:
            return m
    return None


def _pick_execution_price(m: Dict[str, Any]) -> Optional[float]:
    """
    Mirror your backtest execution: prefer ask, then mid (price), then bid.
    """
    yes_ask = m.get("yes_ask_prob")
    mid = m.get("price")
    yes_bid = m.get("yes_bid_prob")

    for v in (yes_ask, mid, yes_bid):
        if v is not None and v > 0.0:
            return float(v)
    return None


@dataclass
class Position:
    market_id: str
    avg_price: float
    contracts: float
    dollars_at_risk: float


class BaseBroker:
    """
    Minimal broker interface that the live engine + strategies rely on.
    """

    def portfolio_view(self) -> Dict[str, Any]:
        raise NotImplementedError

    def execute_intents(self, intents: List[TradeIntent], state: Dict[str, Any]) -> None:
        raise NotImplementedError

    def on_state_processed(self, state: Dict[str, Any]) -> None:
        # Hook for logging / metrics; no-op for now.
        return


@dataclass
class InMemoryBroker(BaseBroker):
    """
    Paper-trading broker:
      - Tracks cash + positions in memory
      - Applies TradeIntent(open/close) using current state prices
      - Logs fills in self.trade_log
    """

    cash: float = 10_000.0
    positions: Dict[str, Position] = field(default_factory=dict)
    trade_log: List[Dict[str, Any]] = field(default_factory=list)
    realized_pnl: float = 0.0

    # ---------- Public API used by strategies/engine ----------

    def portfolio_view(self) -> Dict[str, Any]:
        """
        Shape matches what your strategies expect:
          {
            "cash": float,
            "positions": {
              market_id: {
                "market_id": str,
                "avg_price": float,
                "contracts": float,
                "dollars_at_risk": float,
              },
              ...
            }
          }
        """
        return {
            "cash": self.cash,
            "positions": {
                mid: {
                    "market_id": p.market_id,
                    "avg_price": p.avg_price,
                    "contracts": p.contracts,
                    "dollars_at_risk": p.dollars_at_risk,
                }
                for mid, p in self.positions.items()
            },
        }

    def execute_intents(self, intents: List[TradeIntent], state: Dict[str, Any]) -> None:
        for intent in intents:
            self._execute_intent(intent, state)

    # ---------- Internal helpers ----------

    def _execute_intent(self, intent: TradeIntent, state: Dict[str, Any]) -> None:
        if intent.action not in ("open", "close"):
            print(f"[broker] ignoring unsupported action {intent.action!r}")
            return

        market_id = intent.market_id
        m = _find_market_in_state(state, market_id)
        if not m:
            print(f"[broker] no market {market_id} in state; skipping intent")
            return

        px = _pick_execution_price(m)
        if px is None:
            print(f"[broker] no usable price for {market_id}; skipping intent")
            return

        ts_str = state.get("timestamp")
        try:
            ts = datetime.fromisoformat(ts_str) if isinstance(
                ts_str, str) else datetime.utcnow()
        except Exception:
            ts = datetime.utcnow()

        if intent.action == "open":
            self._open_position(market_id, px, intent.position_size, ts)
        elif intent.action == "close":
            self._close_position(market_id, px, ts)

    def _open_position(self, market_id: str, price: float, dollars: float, ts: datetime) -> None:
        if dollars <= 0.0:
            return

        contracts = dollars / price  # yes-shares notionally
        pos = self.positions.get(market_id)

        if pos:
            # Simple weighted-avg price update
            total_dollars = pos.dollars_at_risk + dollars
            if total_dollars > 0:
                new_avg = (pos.avg_price * pos.dollars_at_risk +
                           price * dollars) / total_dollars
            else:
                new_avg = price

            pos.avg_price = new_avg
            pos.contracts += contracts
            pos.dollars_at_risk += dollars
        else:
            self.positions[market_id] = Position(
                market_id=market_id,
                avg_price=price,
                contracts=contracts,
                dollars_at_risk=dollars,
            )

        self.cash -= dollars  # treat as cash outlay
        self.trade_log.append(
            {
                "ts": ts.isoformat(),
                "side": "buy",
                "market_id": market_id,
                "price": price,
                "contracts": contracts,
                "dollars": dollars,
            }
        )

    def _close_position(self, market_id: str, price: float, ts: datetime) -> None:
        pos = self.positions.get(market_id)
        if not pos:
            return

        # Simple close-all
        contracts = pos.contracts
        dollars_in = pos.dollars_at_risk
        dollars_out = contracts * price
        pnl = dollars_out - dollars_in

        self.cash += dollars_out
        self.realized_pnl += pnl
        del self.positions[market_id]

        self.trade_log.append(
            {
                "ts": ts.isoformat(),
                "side": "sell",
                "market_id": market_id,
                "price": price,
                "contracts": contracts,
                "dollars_in": dollars_in,
                "dollars_out": dollars_out,
                "pnl": pnl,
            }
        )
