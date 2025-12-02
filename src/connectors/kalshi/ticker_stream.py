# src/connectors/kalshi/ticker_stream.py
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List

import websockets

from src.connectors.kalshi.auth import WS_URL, build_ws_headers


async def ticker_stream(market_tickers: List[str]) -> AsyncIterator[Dict[str, Any]]:
    """
    Async generator yielding normalized ticker messages for the given market_tickers.

    Yields dicts:
      {
        "ts_iso": str,
        "kalshi_ts": int | float | None,
        "market_ticker": str,
        "price_prob": float | None,
        "yes_bid_prob": float | None,
        "yes_ask_prob": float | None,
        "volume": Any,
        "open_interest": Any,
        "status": Any,
      }
    """
    while True:
        headers = build_ws_headers()
        try:
            async with websockets.connect(
                WS_URL,
                additional_headers=headers,  # IMPORTANT: this matches your scraper code
            ) as ws:
                sub_msg = {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["ticker"],
                        "market_tickers": market_tickers,
                    },
                }
                await ws.send(json.dumps(sub_msg))
                print(
                    f"[ticker_stream] subscribed to {len(market_tickers)} markets: "
                    f"{market_tickers}"
                )

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if msg.get("type") != "ticker":
                        continue

                    payload = msg.get("msg") or {}
                    market_ticker = payload.get("market_ticker")
                    if not market_ticker:
                        continue

                    kalshi_ts = payload.get("ts")

                    if isinstance(kalshi_ts, (int, float)):
                        ts_iso = datetime.fromtimestamp(
                            kalshi_ts, tz=timezone.utc
                        ).isoformat()
                    else:
                        ts_iso = datetime.now(timezone.utc).isoformat()

                    def norm_cents(field: str) -> float | None:
                        v = payload.get(field)
                        if v is None:
                            return None
                        try:
                            return float(v) / 100.0
                        except Exception:
                            return None

                    yield {
                        "ts_iso": ts_iso,
                        "kalshi_ts": kalshi_ts,
                        "market_ticker": market_ticker,
                        "price_prob": norm_cents("price"),
                        "yes_bid_prob": norm_cents("yes_bid"),
                        "yes_ask_prob": norm_cents("yes_ask"),
                        "volume": payload.get("volume"),
                        "open_interest": payload.get("open_interest"),
                        "status": payload.get("status"),
                    }

        except Exception as e:
            print(f"[ticker_stream] WS error: {e!r}; reconnecting in 3s...")
            await asyncio.sleep(3.0)
