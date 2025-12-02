# src/core/execution.py

import math

from src.core.models import Position, Trade
from src.core.portfolio import PortfolioState


def apply_intent(intent, state, portfolio: PortfolioState) -> None:
    market = _get_market(state, intent.market_id)
    if market is None:
        return

    price = _get_execution_price(market, intent.action)
    if price is None or price <= 0.0:
        return

    if intent.action == "open":
        _open_position(intent, market, price, state, portfolio)
    elif intent.action == "close":
        _close_position(intent.market_id, price, state, portfolio)


def auto_settle(state, portfolio: PortfolioState) -> None:
    game_id = state["game_id"]

    score_home = state.get("score_home")
    score_away = state.get("score_away")
    if score_home is None or score_away is None:
        return

    if score_home > score_away:
        winning_team = state["home_team"]
    elif score_away > score_home:
        winning_team = state["away_team"]
    else:
        winning_team = None

    if winning_team is None:
        return

    for mid, pos in list(portfolio.positions.items()):
        if pos.game_id != game_id:
            continue

        is_win = (pos.team == winning_team)
        settlement_price = 1.0 if is_win else 0.0

        _close_position(mid, settlement_price, state, portfolio, auto=True)


# -------------------------
# Internal helpers
# -------------------------

def _get_execution_price(market, action: str):
    yes_bid = market.get("yes_bid_prob")
    yes_ask = market.get("yes_ask_prob")
    mid = market.get("price")

    if action == "open":
        if yes_ask is not None:
            return yes_ask
        if mid is not None:
            return mid
        return yes_bid

    if action == "close":
        if yes_bid is not None:
            return yes_bid
        if mid is not None:
            return mid
        return yes_ask

    return None


def _calc_fee(contracts: float, price: float, fee_rate: float = 0.07) -> float:
    if contracts <= 0 or price is None or price <= 0 or price >= 1:
        return 0.0
    raw = fee_rate * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0) / 100.0


def _open_position(intent, market, price, state, portfolio: PortfolioState) -> None:
    size = intent.position_size
    if price is None or price <= 0.0:
        return

    contracts = size / price
    open_fee = _calc_fee(contracts, price)

    game_id = state["game_id"]
    team = market.get("team")

    pos = Position(
        market_id=intent.market_id,
        game_id=game_id,
        team=team,
        contracts=contracts,
        entry_price=price,
        open_fee=open_fee,
    )
    portfolio.positions[intent.market_id] = pos

    portfolio.cash -= (size + open_fee)

    portfolio.trade_log.append(
        Trade(
            timestamp=state["timestamp"],
            market_id=intent.market_id,
            action="open",
            price=price,
            contracts=contracts,
            pnl=0.0,
        )
    )


def _close_position(market_id, price, state, portfolio: PortfolioState, auto: bool = False) -> None:
    pos = portfolio.positions.get(market_id)
    if not pos or price is None or price < 0.0:
        return

    close_fee = _calc_fee(pos.contracts, price) if not auto else 0.0

    proceeds = pos.contracts * price
    portfolio.cash += (proceeds - close_fee)
    del portfolio.positions[market_id]

    pnl = pos.contracts * (price - pos.entry_price) - pos.open_fee - close_fee

    portfolio.trade_log.append(
        Trade(
            timestamp=state["timestamp"],
            market_id=market_id,
            action="auto_close" if auto else "close",
            price=price,
            contracts=pos.contracts,
            pnl=pnl,
        )
    )


def _get_market(state, market_id):
    for m in state.get("markets", []):
        if m.get("market_id") == market_id:
            return m
    return None
