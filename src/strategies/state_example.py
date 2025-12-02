state = {
    "timestamp": "2024-01-15T02:48:00Z",
    "game_id": 301245,
    "home_team": "GSW",
    "away_team": "SAS",
    "score_home": 102,
    "score_away": 98,
    "score_diff": 4,
    "quarter": 4,
    "time_remaining_minutes": 8.3,
    "time_remaining_quarter_seconds": 510,

    "markets": [
        {
            # Static / identifiers
            "market_id": "NBA.GSW.SAS.ML.HOME",
            "type": "moneyline",
            "team": "GSW",
            "side": "home",
            "line": None,

            # Time-varying from candlesticks
            "price": 0.60,         # from candlestick.price.close / 100
            "yes_bid_prob": 0.59,  # from candlestick.yes_bid.close / 100
            "yes_ask_prob": 0.61,  # from candlestick.yes_ask.close / 100
            "bid_ask_spread": 0.02,
            "volume": 1234,        # candlestick.volume
            "open_interest": 800,  # candlestick.open_interest

            # Status / timing from market metadata
            "open_time": "2024-01-15T00:05:00Z",
            "close_time": "2024-01-15T03:30:00Z",
            "expiration_time": "2024-01-15T03:35:00Z",
            "status": "active",    # from get_market / get_markets
            "result": None,        # "yes" / "no" / None

            # Descriptive (optional)
            "market_title": "Will the Warriors win?",
            "market_subtitle": "Regular season game",
            "rules_primary": "Warriors must win in regulation or OT",
        },
        # away ML, spreads, totals...
    ],
}
