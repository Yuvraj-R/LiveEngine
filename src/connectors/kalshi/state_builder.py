from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from src.core.models import BaseMarket, BaseState
from .ws_stream import kalshi_ticker_stream


@dataclass
class MarketGroupConfig:
    """
    A logical group of markets that define ONE state stream.

    Example:
      event_ticker="KXNBAGAME-25NOV22LALUTA"
      market_tickers=[..., ...]
      market_type="binary" or "moneyline" etc.
    """
    event_ticker: str
    market_tickers: List[str]
    market_type: str = "binary"   # generic; domain can override meaning


def _norm_cents(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val) / 100.0
    except Exception:
        return None


async def kalshi_state_stream(
    cfg: MarketGroupConfig,
) -> AsyncIterator[BaseState]:
    """
    Async generator:
      raw Kalshi ticker msgs → aggregated BaseState per tick.

    At each tick:
      - update snapshot for the specific market
      - emit a BaseState with ALL current markets in the group
    """
    last_snapshots: Dict[str, BaseMarket] = {}

    async for payload in kalshi_ticker_stream(cfg.market_tickers):
        mkt = payload.get("market_ticker")
        if mkt not in cfg.market_tickers:
            continue

        kalshi_ts = payload.get("ts")  # seconds since epoch
        if isinstance(kalshi_ts, (int, float)):
            ts_dt = datetime.fromtimestamp(kalshi_ts, tz=timezone.utc)
        else:
            ts_dt = datetime.now(timezone.utc)

        ts_iso = ts_dt.isoformat()

        price = _norm_cents(payload.get("price"))
        yes_bid = _norm_cents(payload.get("yes_bid"))
        yes_ask = _norm_cents(payload.get("yes_ask"))

        spread: Optional[float] = None
        if yes_bid is not None and yes_ask is not None:
            spread = yes_ask - yes_bid

        status = payload.get("status")
        if isinstance(status, str):
            status = status.lower()
        else:
            status = None

        snapshot = BaseMarket(
            market_id=mkt,
            event_ticker=cfg.event_ticker,
            type=cfg.market_type,
            price=price,
            yes_bid_prob=yes_bid,
            yes_ask_prob=yes_ask,
            bid_ask_spread=spread,
            volume=payload.get("volume"),
            open_interest=payload.get("open_interest"),
            status=status,
            result=None,
            meta={"raw": payload},
        )
        last_snapshots[mkt] = snapshot

        state = BaseState(
            timestamp=ts_iso,
            event_ticker=cfg.event_ticker,
            markets=list(last_snapshots.values()),
            # domain-specific context (NBA, etc.) gets added upstream
            context={},
        )
        yield state
