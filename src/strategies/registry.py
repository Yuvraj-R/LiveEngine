from .situational.deficit_recovery import DeficitRecoveryStrategy
from .base.price_logger import PriceLoggerStrategy
from .situational.late_game_underdog import LateGameUnderdogStrategy
from .situational.tight_game_coinflip import TightGameCoinflipStrategy
from .mean_reversion.no_score_spike_revert import NoScoreSpikeRevertStrategy
from .momentum.micro_momentum_follow import MicroMomentumFollowStrategy
from .mean_reversion.panic_spread_fade import PanicSpreadFadeStrategy
from .mean_reversion.late_game_shock_fade import LateGameShockFadeStrategy
from .momentum.price_shock_momentum import PriceShockMomentumStrategy
from .situational.underdog_resilience import UnderdogResilienceStrategy

STRATEGY_REGISTRY = {
    "late_game_underdog": LateGameUnderdogStrategy,
    "tight_game_coinflip": TightGameCoinflipStrategy,
    "no_score_spike_revert": NoScoreSpikeRevertStrategy,
    "micro_momentum_follow": MicroMomentumFollowStrategy,
    "panic_spread_fade": PanicSpreadFadeStrategy,
    "late_game_shock_fade": LateGameShockFadeStrategy,
    "price_shock_momentum": PriceShockMomentumStrategy,
    "underdog_resilience": UnderdogResilienceStrategy,
    "price_logger": PriceLoggerStrategy,
    "deficit_recovery": DeficitRecoveryStrategy,
}


def get_strategy_class(name: str):
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy: {name}")
    return STRATEGY_REGISTRY[name]
