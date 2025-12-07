# src/connectors/kalshi/nfl_state_merger.py
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Iterable, Optional

from src.core.nfl_models import (
    NFLMoneylineMarket,
    NFLScoreboardSnapshot,
    build_nfl_state_dict,
)


@dataclass
class KalshiTick:
    """
    Normalized Kalshi ticker event.
    (Identical to NBA version, repeated here for isolation/stability).
    """
    ts_iso: datetime
    market_ticker: str
    price_prob: Optional[float] = None
    yes_bid_prob: Optional[float] = None
    yes_ask_prob: Optional[float] = None
    volume: Optional[float] = None
    open_interest: Optional[float] = None
    status: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "KalshiTick":
        ts_raw = raw.get("ts_iso")
        if isinstance(ts_raw, str):
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.now(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        def _safe_float(v: Any) -> Optional[float]:
            if v is None:
                return None
            try:
                return float(v)
            except:
                return None

        return cls(
            ts_iso=ts,
            market_ticker=str(raw.get("market_ticker") or ""),
            price_prob=_safe_float(raw.get("price_prob")),
            yes_bid_prob=_safe_float(raw.get("yes_bid_prob")),
            yes_ask_prob=_safe_float(raw.get("yes_ask_prob")),
            volume=_safe_float(raw.get("volume")),
            open_interest=_safe_float(raw.get("open_interest")),
            status=(raw.get("status") or None),
        )


async def merge_nfl_and_kalshi_streams(
    *,
    event_ticker: str,
    game_id: str,
    home_team: str,
    away_team: str,
    tick_stream: AsyncIterator[Dict[str, Any]],
    scoreboard_stream: AsyncIterator[NFLScoreboardSnapshot],
    initial_markets: Optional[Iterable[str]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Clock-Driven Merger for NFL.
    Produces a state emission at least every 1 second, OR whenever a Kalshi tick arrives.
    """

    # 1. Internal State
    latest_score: Optional[NFLScoreboardSnapshot] = None
    markets: Dict[str, NFLMoneylineMarket] = {}

    # Seed markets
    if initial_markets:
        for mt in initial_markets:
            mt_str = str(mt)
            markets[mt_str] = NFLMoneylineMarket(
                market_id=mt_str, event_ticker=event_ticker, type="moneyline",
                price=None, yes_bid_prob=None, yes_ask_prob=None, volume=None,
                open_interest=None, status=None, meta={}, team=None, side="unknown", line=None
            )

    # 2. Queues for async decoupling
    tick_queue = asyncio.Queue()
    score_queue = asyncio.Queue()

    # 3. Background Consumers
    async def _consume_ticks():
        async for t in tick_stream:
            await tick_queue.put(t)
        await tick_queue.put(None)  # Sentinel

    async def _consume_scores():
        async for s in scoreboard_stream:
            await score_queue.put(s)
        await score_queue.put(None)

    # Launch tasks
    t_task = asyncio.create_task(_consume_ticks())
    s_task = asyncio.create_task(_consume_scores())

    # 4. Main Event Loop (Clock-Driven)
    last_emit = datetime.now(timezone.utc)
    keep_running = True

    # Flags to track if streams are alive
    ticks_alive = True
    scores_alive = True

    while keep_running:
        if not ticks_alive and not scores_alive:
            break

        did_update = False

        # A. Drain Score Updates (Take latest only)
        new_score = None
        while not score_queue.empty():
            item = score_queue.get_nowait()
            if item is None:
                scores_alive = False
            else:
                new_score = item

        if new_score:
            latest_score = new_score
            did_update = True

        # B. Process Ticks (Process ALL to catch every price change)
        while not tick_queue.empty():
            raw_tick = tick_queue.get_nowait()
            if raw_tick is None:
                ticks_alive = False
                continue

            tick = KalshiTick.from_raw(raw_tick)
            mt = tick.market_ticker
            if not mt:
                continue

            m = markets.get(mt)
            if not m:
                m = NFLMoneylineMarket(
                    market_id=mt, event_ticker=event_ticker, type="moneyline",
                    team=None, side="unknown"
                )
                markets[mt] = m

            # Apply updates
            if tick.price_prob is not None:
                m["price"] = tick.price_prob
            if tick.yes_bid_prob is not None:
                m["yes_bid_prob"] = tick.yes_bid_prob
            if tick.yes_ask_prob is not None:
                m["yes_ask_prob"] = tick.yes_ask_prob
            if tick.volume is not None:
                m["volume"] = tick.volume
            if tick.open_interest is not None:
                m["open_interest"] = tick.open_interest
            if tick.status is not None:
                m["status"] = tick.status

            # Infer side (NFL logic is same as NBA: suffix match)
            if m.get("team") is None and "-" in mt:
                suffix = mt.split("-")[-1]
                if suffix in (home_team, away_team):
                    m["team"] = suffix
                    m["side"] = "home" if suffix == home_team else "away"

            # Emit IMMEDIATELY on price change
            if latest_score:
                yield build_nfl_state_dict(latest_score, markets, event_ticker=event_ticker, ts_iso=tick.ts_iso.isoformat())
                last_emit = datetime.now(timezone.utc)
                did_update = True

        # C. Heartbeat Emission (Clock-Driven)
        # Force emission if 1.0s has passed without activity
        now = datetime.now(timezone.utc)
        if latest_score and (now - last_emit).total_seconds() >= 1.0:
            yield build_nfl_state_dict(latest_score, markets, event_ticker=event_ticker, ts_iso=now.isoformat())
            last_emit = now
            did_update = True

        # D. Throttle
        if not did_update:
            await asyncio.sleep(0.1)

    # Cleanup
    t_task.cancel()
    s_task.cancel()
    with suppress(asyncio.CancelledError):
        await t_task
        await s_task
