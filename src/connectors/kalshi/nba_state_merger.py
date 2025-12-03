# src/connectors/kalshi/nba_state_merger.py
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Iterable, Optional

from src.core.nba_models import (
    NBAMoneylineMarket,
    NBAScoreboardSnapshot,
    build_nba_state_dict,
)


@dataclass
class KalshiTick:
    """
    Normalized Kalshi ticker event coming off your WS stream.
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
            except (TypeError, ValueError):
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


async def merge_nba_and_kalshi_streams(
    *,
    event_ticker: str,
    game_id: str,
    home_team: str,
    away_team: str,
    tick_stream: AsyncIterator[Dict[str, Any]],
    scoreboard_stream: AsyncIterator[NBAScoreboardSnapshot],
    initial_markets: Optional[Iterable[str]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Merge Kalshi ticker stream + NBA scoreboard snapshots into engine-ready
    NBA state dicts that match your backtest format.
    """
    latest_score: Optional[NBAScoreboardSnapshot] = None
    markets: Dict[str, NBAMoneylineMarket] = {}

    # Seed with known markets if provided
    if initial_markets:
        for mt in initial_markets:
            mt_str = str(mt)
            markets[mt_str] = NBAMoneylineMarket(
                market_id=mt_str,
                event_ticker=event_ticker,
                type="moneyline",
                price=None,
                yes_bid_prob=None,
                yes_ask_prob=None,
                volume=None,
                open_interest=None,
                status=None,
                meta={},
                team=None,
                side="unknown",
                line=None,
            )

    score_done = asyncio.Event()

    async def _scoreboard_worker() -> None:
        nonlocal latest_score
        async for snap in scoreboard_stream:
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

            # upsert market snapshot
            m = markets.get(mt)
            if m is None:
                m = NBAMoneylineMarket(
                    market_id=mt,
                    event_ticker=event_ticker,
                    type="moneyline",
                    price=tick.price_prob,
                    yes_bid_prob=tick.yes_bid_prob,
                    yes_ask_prob=tick.yes_ask_prob,
                    volume=tick.volume,
                    open_interest=tick.open_interest,
                    status=tick.status,
                    meta={},
                    team=None,
                    side="unknown",
                    line=None,
                )
                markets[mt] = m
            else:
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

            if latest_score is None:
                # no scoreboard yet → can't build a full merged state
                continue

            # Infer team/side from ticker suffix (e.g. ...-BOS)
            if m.get("team") is None and "-" in mt:
                suffix = mt.split("-")[-1]
                if suffix in (home_team, away_team):
                    m["team"] = suffix
                    m["side"] = "home" if suffix == home_team else "away"

            state_dict = build_nba_state_dict(
                scoreboard=latest_score,
                markets=markets,
                event_ticker=event_ticker,
                ts_iso=tick.ts_iso.isoformat(),
            )

            yield state_dict

        # once Kalshi ticker ends, wait for scoreboard to mark FINAL
        await score_done.wait()

    finally:
        sb_task.cancel()
        with suppress(asyncio.CancelledError):
            await sb_task
