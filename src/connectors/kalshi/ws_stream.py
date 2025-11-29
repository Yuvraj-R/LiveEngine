from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List

import websockets  # from requirements.txt

from .auth import create_ws_headers

WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
INACTIVITY_RECONNECT_SECS = 90.0


async def kalshi_ticker_stream(
    market_tickers: List[str],
) -> AsyncIterator[Dict[str, Any]]:
    """
    Async generator yielding raw Kalshi ticker payloads for the given
    market_tickers.

    Yields the 'msg' dict for messages with type == 'ticker'.
    Handles reconnect-on-idle.
    """
    if not market_tickers:
        raise ValueError(
            "kalshi_ticker_stream requires at least one market_ticker")

    while True:
        headers = create_ws_headers()
        try:
            async with websockets.connect(
                WS_URL,
                additional_headers=headers,
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

                last_ticker_ts = datetime.now(timezone.utc)

                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    except asyncio.TimeoutError:
                        idle = (datetime.now(timezone.utc) -
                                last_ticker_ts).total_seconds()
                        if idle > INACTIVITY_RECONNECT_SECS:
                            print(
                                f"[kalshi_ticker_stream] idle {idle:.0f}s, reconnecting..."
                            )
                            break
                        continue

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if msg.get("type") != "ticker":
                        continue

                    last_ticker_ts = datetime.now(timezone.utc)
                    payload = msg.get("msg") or {}
                    yield payload

        except Exception as e:  # noqa: BLE001
            print(f"[kalshi_ticker_stream] WS error: {e!r}, backing off...")
            await asyncio.sleep(5.0)
