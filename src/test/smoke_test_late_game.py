# scripts/smoke_test_late_game.py (optional)

from src.core.models import BaseState
from src.engine.broker import PaperBroker
from src.engine.live_engine import run_strategy_on_stream
from src.strategies.late_game_underdog import LateGameUnderdogStrategy


def fake_states():
    yield BaseState(
        timestamp="2025-11-25T03:00:00Z",
        event_ticker="KXNBAGAME-FAKE",
        markets=[
            {
                "market_id": "KXNBAGAME-FAKE-HOME",
                "event_ticker": "KXNBAGAME-FAKE",
                "type": "moneyline",
                "price": 0.10,
                "yes_bid_prob": 0.09,
                "yes_ask_prob": 0.11,
                "meta": {},
            },
            {
                "market_id": "KXNBAGAME-FAKE-AWAY",
                "event_ticker": "KXNBAGAME-FAKE",
                "type": "moneyline",
                "price": 0.30,
                "yes_bid_prob": 0.29,
                "yes_ask_prob": 0.31,
                "meta": {},
            },
        ],
        context={},
        quarter=4,
        time_remaining_minutes=2.0,
        score_diff=3.0,
    )


def main():
    strat = LateGameUnderdogStrategy()
    broker = PaperBroker()
    run_strategy_on_stream(strat, fake_states(), broker)
    print("Final cash:", broker.cash)
    print("Positions:", broker.positions)


if __name__ == "__main__":
    main()
