# src/connectors/kalshi/ticker_stream.py

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import websockets

from src.connectors.kalshi.auth import KalshiAuth

WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
INACTIVITY_RECONNECT_SECS = 90.0


def _norm_cents(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val) / 100.0
    except Exception:
        return None


async def ticker_stream(
    market_tickers: List[str],
) -> AsyncIterator[Dict[str, Any]]:
    """
    Async generator yielding normalized ticker messages for the given market_tickers.

    Each yielded dict looks like:
      {
        "ts_iso": str,
        "kalshi_ts": int | float | None,
        "market_ticker": str,
        "price_prob": float | None,
        "yes_bid_prob": float | None,
        "yes_ask_prob": float | None,
        "volume": ...,
        "open_interest": ...,
        "status": str | None,
        "raw": original_msg_dict,
      }
    """
    if not market_tickers:
        raise ValueError("ticker_stream requires at least one market_ticker")

    auth = KalshiAuth.from_env()

    while True:
        headers = auth.build_ws_headers()
        try:
            async with websockets.connect(WS_URL, additional_headers=headers) as ws:
                print(
                    f"[ticker_stream] Connected. Subscribing to {len(market_tickers)} markets."
                )
                sub_msg = {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["ticker"],
                        "market_tickers": market_tickers,
                    },
                }
                await ws.send(json.dumps(sub_msg))

                last_ticker_ts = datetime.now(timezone.utc)

                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    except asyncio.TimeoutError:
                        idle = (datetime.now(timezone.utc) -
                                last_ticker_ts).total_seconds()
                        if idle > INACTIVITY_RECONNECT_SECS:
                            print(
                                f"[ticker_stream] Idle for {idle:.0f}s; reconnecting WebSocket."
                            )
                            break
                        else:
                            continue

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("type")
                    if msg_type == "subscribed":
                        continue
                    if msg_type != "ticker":
                        continue

                    payload = msg.get("msg") or {}
                    mkt = payload.get("market_ticker")
                    if mkt not in market_tickers:
                        continue

                    last_ticker_ts = datetime.now(timezone.utc)

                    kalshi_ts = payload.get("ts")
                    if isinstance(kalshi_ts, (int, float)):
                        ts_iso = datetime.fromtimestamp(
                            kalshi_ts, tz=timezone.utc
                        ).isoformat()
                    else:
                        ts_iso = datetime.now(timezone.utc).isoformat()

                    event = {
                        "ts_iso": ts_iso,
                        "kalshi_ts": kalshi_ts,
                        "market_ticker": mkt,
                        "price_prob": _norm_cents(payload.get("price")),
                        "yes_bid_prob": _norm_cents(payload.get("yes_bid")),
                        "yes_ask_prob": _norm_cents(payload.get("yes_ask")),
                        "volume": payload.get("volume"),
                        "open_interest": payload.get("open_interest"),
                        "status": payload.get("status"),
                        "raw": msg,
                    }

                    yield event

        except Exception as e:
            print(
                f"[ticker_stream] WS error: {e!r}; backing off before reconnect.")
            await asyncio.sleep(5.0)
            continue
