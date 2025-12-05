from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from .auth import API_BASE, build_auth_headers


class KalshiHTTPClient:
    """
    Thin, low-level REST client for Kalshi.
    Synchronous methods; caller should wrap in asyncio.to_thread if needed.
    """

    def __init__(self, *, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------ #
    # Core request helper
    # ------------------------------------------------------------------ #

    def _request(
        self,
        method: str,
        route: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not route.startswith("/"):
            raise ValueError("route must start with '/' (e.g. '/markets')")

        url = API_BASE + route
        headers = build_auth_headers(method, route)

        resp = self._session.request(
            method=method.upper(),
            url=url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=self.timeout,
        )
        resp.raise_for_status()

        if not resp.content:
            return {}
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}

    # ------------------------------------------------------------------ #
    # Endpoints
    # ------------------------------------------------------------------ #

    def get_market(self, ticker: str) -> Dict[str, Any]:
        """GET /markets/{ticker}"""
        route = f"/markets/{ticker}"
        return self._request("GET", route)

    def get_balance(self) -> Dict[str, Any]:
        """
        GET /portfolio/balance
        Returns dict like: {"balance": 123456} (cents)
        """
        return self._request("GET", "/portfolio/balance")

    def get_portfolio_positions(self) -> Dict[str, Any]:
        """
        GET /portfolio/positions
        Useful for syncing state on startup.
        """
        return self._request("GET", "/portfolio/positions")

    def place_order(
        self,
        *,
        market_ticker: str,
        side: str,
        price_cents: int,
        count: int,
        action: str = "buy",  # <--- NEW ARGUMENT
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /portfolio/orders

        :param side: "yes" or "no"
        :param action: "buy" or "sell" (Required for closing positions)
        :param price_cents: limit price in cents (1-99)
        :param count: number of contracts
        """
        side = side.lower()
        if side not in {"yes", "no"}:
            raise ValueError("side must be 'yes' or 'no'")

        action = action.lower()
        if action not in {"buy", "sell"}:
            raise ValueError("action must be 'buy' or 'sell'")

        # In Kalshi v2, we usually only trade 'yes' side, but buy/sell determines direction.
        # But we pass side explicitly just in case.

        body: Dict[str, Any] = {
            "ticker": market_ticker,
            "action": action,
            "type": "limit",
            "side": side,
            "count": int(count),
        }

        if side == "yes":
            body["yes_price"] = int(price_cents)
        else:
            body["no_price"] = int(price_cents)

        if client_order_id:
            body["client_order_id"] = client_order_id

        return self._request("POST", "/portfolio/orders", json_body=body)
