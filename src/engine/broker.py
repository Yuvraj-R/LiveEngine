from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, Tuple

from src.connectors.kalshi.http_client import KalshiHTTPClient
from src.strategies.base.strategy import TradeIntent


log = logging.getLogger(__name__)


@dataclass
class OrderResult:
    ok: bool
    order_id: str | None = None
    error: str | None = None
    raw: Dict[str, Any] | None = None


class Broker(Protocol):
    async def execute(self, intent: TradeIntent, state: Dict[str, Any]) -> OrderResult:
        ...

    def get_portfolio_view(self) -> Dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# Mock broker (used by tests / dry runs)
# ---------------------------------------------------------------------------

class MockBroker(Broker):
    def __init__(self) -> None:
        self.orders: List[Tuple[TradeIntent, Dict[str, Any]]] = []
        self._positions: Dict[str, Dict[str, Any]] = {}

    def get_portfolio_view(self) -> Dict[str, Any]:
        # Very simple view: only dollars_at_risk per market
        return {"positions": dict(self._positions)}

    async def execute(self, intent: TradeIntent, state: Dict[str, Any]) -> OrderResult:
        if intent.action == "open":
            m_id = intent.market_id
            pos = self._positions.get(m_id)
            stake = float(intent.position_size)
            if pos:
                pos["dollars_at_risk"] += stake
            else:
                self._positions[m_id] = {"dollars_at_risk": stake}

        self.orders.append((intent, state))
        return OrderResult(ok=True, order_id=f"mock-{len(self.orders)}")


# ---------------------------------------------------------------------------
# Real Kalshi broker (default: DRY RUN)
# ---------------------------------------------------------------------------

class KalshiBroker(Broker):
    """
    Live broker that talks to Kalshi's REST API.

    IMPORTANT: defaults to dry_run=True so it NEVER places real orders
    until you explicitly opt-in.
    """

    def __init__(
        self,
        client: KalshiHTTPClient,
        *,
        dry_run: bool = True,
        max_contracts_per_order: int = 2000,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.max_contracts_per_order = max_contracts_per_order

        self._positions: Dict[str, Dict[str, Any]] = {}
        self.orders_log: List[Dict[str, Any]] = []  # records for debugging

    # ---------- portfolio view ----------

    def get_portfolio_view(self) -> Dict[str, Any]:
        return {"positions": dict(self._positions)}

    def _update_positions_local(self, intent: TradeIntent) -> None:
        if intent.action != "open":
            return
        m_id = intent.market_id
        stake = float(intent.position_size)
        pos = self._positions.get(m_id)
        if pos:
            pos["dollars_at_risk"] += stake
        else:
            self._positions[m_id] = {"dollars_at_risk": stake}

    # ---------- helpers ----------

    @staticmethod
    def _effective_open_price_from_state(
        state: Dict[str, Any],
        market_id: str,
    ) -> float | None:
        markets = state.get("markets") or []
        for m in markets:
            if not isinstance(m, dict):
                continue
            if m.get("market_id") != market_id:
                continue

            yes_ask = m.get("yes_ask_prob")
            mid = m.get("price")
            yes_bid = m.get("yes_bid_prob")

            if yes_ask is not None:
                return float(yes_ask)
            if mid is not None:
                return float(mid)
            if yes_bid is not None:
                return float(yes_bid)
            return None
        return None

    def _build_order_payload(
        self,
        intent: TradeIntent,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Map a TradeIntent + state snapshot into an order payload
        (without actually sending it).
        """
        price = self._effective_open_price_from_state(state, intent.market_id)
        if price is None or price <= 0.0:
            raise RuntimeError(
                f"Cannot determine execution price for market {intent.market_id}"
            )

        price_dollars = float(price)
        price_cents = max(1, int(round(price_dollars * 100.0)))

        stake = float(intent.position_size)
        # Rough: stake is "dollars at risk", so contracts ≈ stake / price
        contracts = int(stake / max(price_dollars, 0.01))
        contracts = max(1, min(contracts, self.max_contracts_per_order))

        client_order_id = str(uuid.uuid4())

        payload = {
            "market_ticker": intent.market_id,
            "side": "yes",                # late-game underdog is YES-only for now
            "price_cents": price_cents,
            "count": contracts,
            "client_order_id": client_order_id,
        }
        return payload

    # ---------- main entrypoint ----------

    async def execute(self, intent: TradeIntent, state: Dict[str, Any]) -> OrderResult:
        if intent.action != "open":
            # For now we only support opening YES positions live.
            log.info("Ignoring non-open intent for now: %r", intent)
            return OrderResult(ok=True, order_id=None)

        try:
            payload = self._build_order_payload(intent, state)
        except Exception as e:  # noqa: BLE001
            log.exception("Failed to build order payload")
            return OrderResult(ok=False, error=str(e))

        record = {
            "intent": intent,
            "state_ts": state.get("timestamp"),
            "payload": payload,
            "dry_run": self.dry_run,
        }

        # Always keep a local log (even in dry-run)
        self.orders_log.append(record)

        if self.dry_run:
            log.info("[KalshiBroker] DRY RUN order: %s", payload)
            self._update_positions_local(intent)
            return OrderResult(
                ok=True,
                order_id=None,
                raw={"dry_run": True, "payload": payload},
            )

        # Real order: run blocking HTTP in a thread
        async def _submit() -> Dict[str, Any]:
            return await asyncio.to_thread(
                self.client.place_order,
                market_ticker=payload["market_ticker"],
                side=payload["side"],
                price_cents=payload["price_cents"],
                count=payload["count"],
                client_order_id=payload["client_order_id"],
            )

        try:
            resp = await _submit()
        except Exception as e:  # noqa: BLE001
            log.exception("Error placing Kalshi order")
            return OrderResult(ok=False, error=str(e))

        self._update_positions_local(intent)

        # Try to extract an order_id if present
        order_id = None
        if isinstance(resp, dict):
            order_id = (
                resp.get("order_id")
                or resp.get("id")
                or (resp.get("order") or {}).get("id")
            )

        return OrderResult(ok=True, order_id=order_id, raw=resp)
