# src/core/backtest.py

from typing import Any, Dict, List

from src.core.portfolio import PortfolioState
from src.core.execution import apply_intent, auto_settle
from src.core.metrics import compute_metrics
from src.core.models import BacktestResult
from src.storage.load_states import load_states_for_config


def run_backtest(strategy, config: Dict[str, Any]) -> BacktestResult:
    portfolio = PortfolioState()
    equity_curve: List[Dict[str, Any]] = []

    states: List[Dict[str, Any]] = load_states_for_config(config)

    for idx, state in enumerate(states):
        equity_before = _compute_equity(state, portfolio)
        portfolio_view = portfolio.get_portfolio_view(equity_before)

        intents = strategy.on_state(state, portfolio_view)
        for intent in intents:
            apply_intent(intent, state, portfolio)

        # game-end detection
        is_final_state = False
        if idx + 1 < len(states):
            curr_gid = state["game_id"]
            next_gid = states[idx + 1]["game_id"]
            if curr_gid != next_gid:
                is_final_state = True
        else:
            is_final_state = True  # last overall

        if is_final_state:
            auto_settle(state, portfolio)

        equity_after = _compute_equity(state, portfolio)
        equity_curve.append(
            {"timestamp": state["timestamp"], "equity": equity_after}
        )

    summary = compute_metrics(
        portfolio.cash,
        equity_curve,
        portfolio.trade_log,
    )

    return BacktestResult(
        summary=summary,
        trades=portfolio.trade_log,
        equity_curve=equity_curve,
    )


def _compute_equity(state, portfolio: PortfolioState) -> float:
    equity = portfolio.cash

    for pos in portfolio.positions.values():
        market = _get_market(state, pos.market_id)
        if not market:
            continue

        mtm_price = market.get("price")

        # If we don't have a usable price here, skip MTM for this tick
        if mtm_price is None:
            continue

        equity += pos.contracts * mtm_price

    return equity


def _get_market(state, market_id):
    for m in state["markets"]:
        if m["market_id"] == market_id:
            return m
    return None
