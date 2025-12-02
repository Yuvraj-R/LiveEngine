# src/connectors/kalshi/nba_state_merger.py

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

from src.core.nba_models import (
    NBAMoneylineMarket,
    NBAScoreboardSnapshot,
    build_nba_state_dict,
)


@dataclass
class KalshiTick:
    """
    Normalized Kalshi ticker event coming off your WS stream.

    We keep it aligned with the JSONL you log in PredictEngine.
    """
    ts_iso: datetime
    event_ticker: str
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

        return cls(
            ts_iso=ts,
            event_ticker=str(raw.get("event_ticker") or ""),
            market_ticker=str(raw.get("market_ticker") or ""),
            price_prob=_safe_float(raw.get("price_prob")),
            yes_bid_prob=_safe_float(raw.get("yes_bid_prob")),
            yes_ask_prob=_safe_float(raw.get("yes_ask_prob")),
            volume=_safe_float(raw.get("volume")),
            open_interest=_safe_float(raw.get("open_interest")),
            status=(raw.get("status") or None),
        )


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


async def merge_nba_and_kalshi_streams(
    *,
    game_id: str,
    home_team: str,
    away_team: str,
    tick_stream: AsyncIterator[Dict[str, Any]],
    scoreboard_stream: AsyncIterator[NBAScoreboardSnapshot],
    initial_markets: Optional[Iterable[str]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Core merge pipeline (Step 3):

    - Consumes raw Kalshi tick dicts (like those you write to JSONL).
    - Consumes NBA scoreboard snapshots for the same game.
    - Maintains latest market snapshots + latest scoreboard.
    - Emits merged 'state' dicts compatible with your backtest engine.

    This does NOT talk to WS or HTTP directly; you wire it up later by
    passing in the appropriate async generators.
    """
    latest_score: Optional[NBAScoreboardSnapshot] = None

    # Initialize containers for market snapshots
    markets: Dict[str, NBAMoneylineMarket] = {}

    if initial_markets:
        for mt in initial_markets:
            markets[str(mt)] = NBAMoneylineMarket(
                market_id=str(mt),
                last_prob=None,
                yes_bid_prob=None,
                yes_ask_prob=None,
                volume=None,
                open_interest=None,
                status=None,
                team=None,
                side="unknown",
            )

    score_done = asyncio.Event()

    async def _scoreboard_worker() -> None:
        nonlocal latest_score
        async for snap in scoreboard_stream:
            # Ensure this is the game we care about
            if snap.game_id != game_id:
                continue
            latest_score = snap
            if snap.status.upper().startswith("FINAL"):
                break
        score_done.set()

    sb_task = asyncio.create_task(_scoreboard_worker())

    try:
        async for raw_tick in tick_stream:
            tick = KalshiTick.from_raw(raw_tick)
            mt = tick.market_ticker
            if not mt:
                continue

            m = markets.get(mt)
            if m is None:
                # new market discovered on the fly
                m = NBAMoneylineMarket(
                    market_id=mt,
                    last_prob=tick.price_prob,
                    yes_bid_prob=tick.yes_bid_prob,
                    yes_ask_prob=tick.yes_ask_prob,
                    volume=tick.volume,
                    open_interest=tick.open_interest,
                    status=tick.status,
                    team=None,
                    side="unknown",
                )
                markets[mt] = m
            else:
                # update existing snapshot
                if tick.price_prob is not None:
                    m.last_prob = tick.price_prob
                if tick.yes_bid_prob is not None:
                    m.yes_bid_prob = tick.yes_bid_prob
                if tick.yes_ask_prob is not None:
                    m.yes_ask_prob = tick.yes_ask_prob
                if tick.volume is not None:
                    m.volume = tick.volume
                if tick.open_interest is not None:
                    m.open_interest = tick.open_interest
                if tick.status is not None:
                    m.status = tick.status

            if latest_score is None:
                # We don't have any scoreboard context yet → skip emitting.
                continue

            # Patch team/side if we can infer from ticker suffix (e.g. ...-BOS)
            # This is optional; if you already know mappings, you can set them
            # before calling this function.
            if m.team is None and "-" in mt:
                suffix = mt.split("-")[-1]
                if suffix in (home_team, away_team):
                    m.team = suffix
                    m.side = "home" if suffix == home_team else "away"

            # Build merged state dict in the exact format your strategy expects
            state_dict = build_nba_state_dict(latest_score, markets)

            # Overwrite timestamp with tick timestamp (more precise)
            state_dict["timestamp"] = tick.ts_iso.isoformat()

            yield state_dict

        # Once tick_stream ends, wait (briefly) for scoreboard to catch up
        await score_done.wait()

    finally:
        sb_task.cancel()
        with suppress(asyncio.CancelledError):
            await sb_task
