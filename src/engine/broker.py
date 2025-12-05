from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, Tuple

from src.connectors.kalshi.http_client import KalshiHTTPClient
from src.strategies.base.strategy import TradeIntent

log = logging.getLogger(__name__)

# HARD SAFETY LIMIT (USD)
# If an order costs more than this, it is rejected internally.
MAX_ORDER_VALUE_SAFETY_CAP = 1000.00


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
# Mock broker (Used for Dry Runs / Backtests)
# ---------------------------------------------------------------------------

class MockBroker(Broker):
    def __init__(self) -> None:
        self.orders: List[Tuple[TradeIntent, Dict[str, Any]]] = []
        self._positions: Dict[str, Dict[str, Any]] = {}

    def get_portfolio_view(self) -> Dict[str, Any]:
        return {"positions": dict(self._positions)}

    async def execute(self, intent: TradeIntent, state: Dict[str, Any]) -> OrderResult:
        m_id = intent.market_id

        # Estimate price for mock
        est_price = getattr(intent, 'price', 0.50) or 0.50

        if intent.action == "open":
            pos = self._positions.get(
                m_id, {"dollars_at_risk": 0.0, "contracts": 0})
            pos["dollars_at_risk"] += float(intent.position_size)
            pos["contracts"] += int(intent.position_size / est_price)
            self._positions[m_id] = pos

        elif intent.action == "close":
            if m_id in self._positions:
                del self._positions[m_id]

        self.orders.append((intent, state))

        # Mock Payload for logger
        mock_count = int(intent.position_size /
                         est_price) if est_price > 0 else 0
        mock_payload = {
            "market_ticker": m_id,
            "side": "yes",
            "action": "buy" if intent.action == "open" else "sell",
            "price_cents": int(est_price * 100),
            "count": mock_count
        }

        return OrderResult(ok=True, order_id=f"mock-{len(self.orders)}", raw={"dry_run": True, "payload": mock_payload})


# ---------------------------------------------------------------------------
# Real Kalshi broker (Hardened)
# ---------------------------------------------------------------------------

class KalshiBroker(Broker):
    """
    Live broker that talks to Kalshi's REST API.
    Enforces Strict Limit Orders, Balance Checks, and Safety Caps.
    """

    def __init__(
        self,
        client: KalshiHTTPClient,
        *,
        dry_run: bool = True,
        max_contracts_per_order: int = 5000,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.max_contracts_per_order = max_contracts_per_order
        self._positions: Dict[str, Dict[str, Any]] = {}

    def get_portfolio_view(self) -> Dict[str, Any]:
        return {"positions": dict(self._positions)}

    def _update_positions_local(self, intent: TradeIntent, executed_contracts: int, executed_price: float) -> None:
        m_id = intent.market_id
        if intent.action == "open":
            pos = self._positions.get(
                m_id, {"dollars_at_risk": 0.0, "contracts": 0})
            pos["dollars_at_risk"] += (executed_contracts * executed_price)
            pos["contracts"] += executed_contracts
            self._positions[m_id] = pos
        elif intent.action == "close":
            # Assume full close for now
            if m_id in self._positions:
                del self._positions[m_id]

    @staticmethod
    def _get_limit_price(state: Dict[str, Any], market_id: str, action: str) -> float | None:
        """
        Determine execution price based on order book.
        OPEN (Buy)  -> Aggressive: Pay ASK
        CLOSE (Sell) -> Aggressive: Hit BID
        """
        markets = state.get("markets") or []
        for m in markets:
            if m.get("market_id") != market_id:
                continue

            yes_ask = m.get("yes_ask_prob")
            yes_bid = m.get("yes_bid_prob")
            last = m.get("price")

            if action == "open":  # Buying YES
                if yes_ask:
                    return float(yes_ask)
                if last:
                    return float(last)
                if yes_bid:
                    return float(yes_bid)
            else:  # Selling YES
                if yes_bid:
                    return float(yes_bid)
                if last:
                    return float(last)
            return None
        return None

    def _build_order_payload(self, intent: TradeIntent, state: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Price
        limit_price = getattr(intent, 'price', None)
        if limit_price is None:
            limit_price = self._get_limit_price(
                state, intent.market_id, intent.action)

        if not limit_price or limit_price <= 0.0 or limit_price > 0.99:
            raise RuntimeError(f"Invalid price calculated: {limit_price}")

        price_cents = int(round(limit_price * 100.0))
        price_cents = max(1, min(99, price_cents))

        # 2. Contracts & Side/Action
        if intent.action == "close":
            pos = self._positions.get(intent.market_id)
            if not pos or pos["contracts"] <= 0:
                raise RuntimeError(
                    f"No position found to close for {intent.market_id}")
            contracts = int(pos["contracts"])
            api_action = "sell"
        else:
            stake = float(intent.position_size)
            contracts = int(stake / limit_price)
            contracts = max(1, min(contracts, self.max_contracts_per_order))
            api_action = "buy"

        # 3. SAFETY CAP
        notional = contracts * (price_cents / 100.0)
        if notional > MAX_ORDER_VALUE_SAFETY_CAP:
            raise RuntimeError(
                f"SAFETY: Order ${notional:.2f} > Cap ${MAX_ORDER_VALUE_SAFETY_CAP}")

        return {
            "market_ticker": intent.market_id,
            "side": "yes",
            "action": api_action,
            "price_cents": price_cents,
            "count": contracts,
            "client_order_id": str(uuid.uuid4())
        }

    async def execute(self, intent: TradeIntent, state: Dict[str, Any]) -> OrderResult:
        # Build Payload
        try:
            payload = self._build_order_payload(intent, state)
        except Exception as e:
            log.error(f"Order Build Error: {e}")
            return OrderResult(ok=False, error=str(e))

        # -------------------------------
        # BALANCE CHECK (Live Buy Only)
        # -------------------------------
        if not self.dry_run and payload["action"] == "buy":
            try:
                bal_resp = await asyncio.to_thread(self.client.get_balance)
                # API returns cents
                balance_cents = int(bal_resp.get("balance", 0))
                cost_cents = payload["count"] * payload["price_cents"]

                # $5.00 Buffer (500 cents)
                if balance_cents < (cost_cents + 500):
                    return OrderResult(ok=False, error=f"Insufficient funds: Have {balance_cents}c, Need {cost_cents}c")
            except Exception as e:
                log.error(f"Balance Check Error: {e}")
                return OrderResult(ok=False, error=f"Balance check failed: {e}")

        # -------------------------------
        # EXECUTE
        # -------------------------------
        if self.dry_run:
            log.info(f"[KalshiBroker] DRY RUN: {payload}")
            self._update_positions_local(
                intent, payload["count"], payload["price_cents"]/100.0)
            return OrderResult(ok=True, order_id=f"dry-{uuid.uuid4()}", raw={"dry_run": True, "payload": payload})

        async def _submit():
            return await asyncio.to_thread(
                self.client.place_order,
                market_ticker=payload["market_ticker"],
                side=payload["side"],
                action=payload["action"],  # Uses new argument
                price_cents=payload["price_cents"],
                count=payload["count"],
                client_order_id=payload["client_order_id"]
            )

        try:
            resp = await _submit()
            self._update_positions_local(
                intent, payload["count"], payload["price_cents"]/100.0)

            # Extract Order ID
            oid = None
            if isinstance(resp, dict):
                oid = resp.get("order_id") or (
                    resp.get("order") or {}).get("order_id")

            return OrderResult(ok=True, order_id=oid, raw=resp)

        except Exception as e:
            log.exception("Order Placement Failed")
            return OrderResult(ok=False, error=str(e))
