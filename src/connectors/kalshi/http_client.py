from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from .auth import API_BASE, build_auth_headers


class KalshiHTTPClient:
    """
    Thin, low-level REST client for Kalshi.

    All methods here are synchronous; callers can wrap in asyncio.to_thread.
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
    # Convenience endpoints we care about first
    # ------------------------------------------------------------------ #

    def get_market(self, ticker: str) -> Dict[str, Any]:
        """
        GET /markets/{ticker}
        """
        route = f"/markets/{ticker}"
        return self._request("GET", route)

    def get_balance(self) -> Dict[str, Any]:
        """
        GET /portfolio/balance
        """
        return self._request("GET", "/portfolio/balance")

    def place_order(
        self,
        *,
        market_ticker: str,
        side: str,
        price_cents: int,
        count: int,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /portfolio/orders

        side: "yes" or "no"
        price_cents: integer [0, 100]
        count: number of contracts
        """
        side = side.lower()
        if side not in {"yes", "no"}:
            raise ValueError("side must be 'yes' or 'no'")

        body: Dict[str, Any] = {
            "ticker": market_ticker,
            "action": "buy" if side == "yes" else "sell",
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
