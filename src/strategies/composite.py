from typing import Any, Dict, List
from src.strategies.base.strategy import Strategy, TradeIntent


class CompositeStrategy(Strategy):
    def __init__(self, strategies: List[Strategy]):
        self.strategies = strategies
        # We don't use self.params or self.state directly here,
        # we delegate to children.

    def on_state(
        self,
        state: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> List[TradeIntent]:

        all_intents = []
        for strat in self.strategies:
            # We inject the strategy name into the intent for logging purposes
            # This requires TradeIntent to allow dynamic attributes or we wrap it
            intents = strat.on_state(state, portfolio)

            for intent in intents:
                # Monkey-patch or attach the strategy name so the Broker knows who sent it
                setattr(intent, 'strategy_name', strat.__class__.__name__)
                all_intents.append(intent)

        return all_intents
