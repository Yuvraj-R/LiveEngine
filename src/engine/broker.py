from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from src.core.models import BaseState, PortfolioView, PositionView
from src.strategies.strategy import TradeIntent


@dataclass
class BrokerConfig:
    starting_cash: float = 10_000.0


class BaseBroker:
    """
    Abstract broker interface.

    Later you can implement:
      - KalshiBroker (real API)
      - PaperBroker (sim / dry-run)
    """

    def get_portfolio_view(self) -> PortfolioView:
        raise NotImplementedError

    def execute(self, state: BaseState, intents: List[TradeIntent]) -> None:
        """
        Apply intents to positions/cash. For live trading, this becomes
        'translate intents -> API calls'.
        """
        raise NotImplementedError


class PaperBroker(BaseBroker):
    """
    Simple in-memory broker for testing the live engine loop.
    Assumes YES-only binary-style trades where price ~ prob in [0, 1].
    """

    def __init__(self, config: BrokerConfig | None = None) -> None:
        cfg = config or BrokerConfig()
        self.cash: float = float(cfg.starting_cash)
        self.positions: Dict[str, PositionView] = {}

    # --------- helpers ---------

    def _mark_to_market(self, state: BaseState) -> float:
        """
        Compute equity = cash + sum(position_value).
        Uses market['price'] as MTM if available.
        """
        equity = self.cash
        markets = {m["market_id"]: m for m in state.get(
            "markets", []) if "market_id" in m}

        for mid, pos in self.positions.items():
            m = markets.get(mid)
            if not m:
                continue
            price = m.get("price")
            if price is None:
                continue
            contracts = float(pos.get("contracts", 0.0))
            equity += contracts * price

        return equity

    def _open_position(self, market_id: str, notional: float, price: float) -> None:
        """
        Simple YES position:
          contracts = notional / price
          cost     = notional
        """
        if notional <= 0.0:
            return

        if price <= 0.0:
            return

        contracts = notional / price
        cost = notional

        self.cash -= cost

        pos = self.positions.get(market_id)
        if pos is None:
            self.positions[market_id] = PositionView(
                market_id=market_id,
                contracts=contracts,
                dollars_at_risk=notional,
                avg_entry_price=price,
                meta={},
            )
        else:
            # naive averaging
            prev_notional = pos.get("dollars_at_risk", 0.0)
            prev_price = pos.get("avg_entry_price") or 0.0
            total_notional = prev_notional + notional
            new_price = (
                (prev_price * prev_notional + price * notional) / total_notional
                if total_notional > 0
                else price
            )
            pos["contracts"] = pos.get("contracts", 0.0) + contracts
            pos["dollars_at_risk"] = total_notional
            pos["avg_entry_price"] = new_price

    # --------- interface ---------

    def get_portfolio_view(self) -> PortfolioView:
        # NOTE: equity will be recomputed per-state in the engine loop,
        # but having a snapshot here is still useful.
        return PortfolioView(
            cash=self.cash,
            equity=self.cash,  # engine will overwrite with MTM
            positions=self.positions,
        )

    def execute(self, state: BaseState, intents: List[TradeIntent]) -> None:
        markets = {m["market_id"]: m for m in state.get(
            "markets", []) if "market_id" in m}

        for intent in intents:
            mid = intent.market_id
            m = markets.get(mid)
            if not m:
                continue

            action = intent.action
            size = float(intent.position_size)

            if action == "open":
                # For now, treat execution price as ask / mid
                p = (
                    m.get("yes_ask_prob")
                    or m.get("price")
                    or m.get("yes_bid_prob")
                )
                if p is None:
                    continue
                self._open_position(mid, size, float(p))

            # TODO: implement "close", "reduce", etc. in later phases
