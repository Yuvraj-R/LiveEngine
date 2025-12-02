# src/core/models.py
from __future__ import annotations
from dataclasses import dataclass

from typing import Any, Dict, List, Optional, TypedDict


# =========================
# Generic market / state
# =========================

class BaseMarket(TypedDict, total=False):
    """
    Generic snapshot of a Kalshi market at a point in time.
    Works for ANY domain (sports, elections, macro, etc.).
    """
    market_id: str              # usually Kalshi market ticker
    event_ticker: str           # parent event, if known

    # Generic classification (not tied to sports):
    # e.g. "binary", "scalar", "moneyline", "spread", "yes_no", etc.
    type: str

    # Price-level info (for binary-style markets, use probs in [0, 1])
    price: Optional[float]
    yes_bid_prob: Optional[float]
    yes_ask_prob: Optional[float]
    bid_ask_spread: Optional[float]

    volume: Optional[float]
    open_interest: Optional[float]

    status: Optional[str]       # "open", "closed", "settled", "finalized", ...
    result: Optional[str]       # "yes", "no", or domain-specific result

    # Arbitrary raw / metadata from Kalshi API
    meta: Dict[str, Any]


class BaseState(TypedDict, total=False):
    """
    Generic snapshot of 'the world' at a time for an event.
    """
    timestamp: str              # ISO8601, UTC
    event_ticker: str
    markets: List[BaseMarket]
    context: Dict[str, Any]


# =========================
# Portfolio views
# =========================

class PositionView(TypedDict, total=False):
    market_id: str
    contracts: float                 # positive for YES, negative for NO if needed
    dollars_at_risk: float
    avg_entry_price: Optional[float]

    # Arbitrary extra data (e.g. realized PnL, tags)
    meta: Dict[str, Any]


class PortfolioView(TypedDict, total=False):
    cash: float
    equity: float
    positions: Dict[str, PositionView]


# =========================
# Backtest / trade models
# =========================


@dataclass
class Position:
    market_id: str
    game_id: str
    team: str
    contracts: float
    entry_price: float
    open_fee: float


@dataclass
class Trade:
    timestamp: str
    market_id: str
    action: str      # "open" | "close" | "auto_close"
    price: float
    contracts: float
    pnl: float


@dataclass
class BacktestResult:
    summary: Dict[str, float]
    trades: List[Trade]
    # [{"timestamp": ..., "equity": ...}]
    equity_curve: List[Dict[str, float]]
