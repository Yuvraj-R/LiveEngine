# LiveEngine

**LiveEngine** is a live sports prediction-market trading system. It discovers games, streams real-time game data (scores, clock) and Kalshi market prices, merges them into a unified state, runs pluggable trading strategies, and executes orders via the Kalshi API—with full support for dry runs, backtesting, and multi-sport (NBA and NFL) workflows.

---

## What It Does

- **Discovery** — For a given date, finds NBA/NFL games and matching Kalshi events (e.g. `KXNBAGAME` series), extracts market tickers (e.g. winner moneyline), and writes job files used by workers.
- **Live workers** — One process per game: connects to Kalshi’s ticker WebSocket and the league scoreboard (NBA CDN or NFL API), merges ticks and score updates into a single clock-driven state stream, runs a composite of enabled strategies, and sends trade intents to a broker.
- **Broker** — `MockBroker` for backtests/dry runs; `KalshiBroker` for live trading (strict limit orders, balance checks, safety cap).
- **Backtesting** — Loads previously recorded merged states from disk, replays them through a strategy, applies intents to a simulated portfolio, settles at game end, and computes metrics. Results are persisted (summary, config, trades CSV, equity curve). A Flask app exposes a POST endpoint to run backtests and return summaries.
- **State recording** — During live runs, merged states are appended to JSON files per game so they can be replayed later for backtests.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Automation (manager.py)                                                │
│  - discover_games (NBA) / nfl.discover_games (NFL)                      │
│  - Saves jobs to src/storage/jobs/                                      │
│  - Spawns one game_worker per game (NBA or NFL worker)                  │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Game worker (game_worker.py or nfl/game_worker.py)                     │
│  - Sleeps until tipoff/kickoff minus N minutes                          │
│  - Kalshi: ticker_stream (WebSocket) + http_client (REST)               │
│  - League: NBAScoreboardClient / NFLScoreboardClient (poll)             │
│  - Merger: merge_nba_and_kalshi_streams / merge_nfl_and_kalshi_streams   │
│  - LiveEngine(CompositeStrategy(strategies), KalshiBroker)               │
│  - State writer appends merged state to disk                           │
│  - On each state: strategy.on_state → intents → broker.execute          │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LiveEngine                                                             │
│  - Consumes async stream of state dicts                                 │
│  - strategy.on_state(state, portfolio_view) → List[TradeIntent]           │
│  - For each intent: broker.execute(intent, state)                       │
└─────────────────────────────────────────────────────────────────────────┘
```

- **Strategies** implement `on_state(state, portfolio) -> List[TradeIntent]`. The registry wires names (e.g. `late_game_underdog`) to classes; the app uses a **CompositeStrategy** so multiple strategies can run in parallel.
- **State** is a dict with `timestamp`, `event_ticker`, `game_id`, `score_home`/`score_away`, `markets` (list of market snapshots with `market_id`, `price`, `yes_bid_prob`, `yes_ask_prob`, `team`, `side`, etc.), and sport-specific `context` (e.g. `nba_raw` / `nfl_raw`).
- **Kalshi** auth uses `.env` (`KALSHI_API_KEY_ID`) and `kalshi_private_key.pem`; REST and WebSocket clients live under `src/connectors/kalshi/`.

---

## Sports and Data Paths

| Sport | Discovery        | Worker module           | State merger              | Config                 | Merged state output                          |
|-------|------------------|-------------------------|---------------------------|------------------------|----------------------------------------------|
| NBA   | `discover_games` | `automation.game_worker`| `nba_state_merger`        | `live_config.json`      | `src/storage/kalshi/merged/states/`          |
| NFL   | `nfl.discover_games` | `automation.nfl.game_worker` | `nfl_state_merger` | `nfl_live_config.json` | `src/storage/kalshi/merged/nfl_states/`      |

Backtest state loading (`load_states_for_config`) uses `config.sport` and the same directories so replay uses the correct merged files.

---

## Strategies (Registry)

Strategies are registered by name in `src/strategies/registry.py`. Active ones are configured per sport in the live configs under `trading.active_strategies` (each has `name`, `enabled`, `params`).

| Name                     | Category      | Description (summary) |
|--------------------------|---------------|------------------------|
| `late_game_underdog`     | Situational   | Late game, underdog within a few points, price below threshold. |
| `tight_game_coinflip`    | Situational   | Very close game, near coin-flip price. |
| `deficit_recovery`       | Situational   | Team was down big, now close, still priced as heavy underdog. |
| `underdog_resilience`    | Situational   | Underdog has stayed close or ahead; fade overreaction. |
| `volatile_underdog_exit` | Situational   | Exit or reduce underdog exposure in volatile late-game conditions. |
| `no_score_spike_revert`  | Mean reversion| Revert after a sharp move with no corresponding score change. |
| `panic_spread_fade`      | Mean reversion| Fade panic after a big spread move. |
| `late_game_shock_fade`   | Mean reversion| Fade late-game price shock. |
| `micro_momentum_follow`  | Momentum      | Short-term momentum following. |
| `price_shock_momentum`   | Momentum      | Follow strong price shock. |
| `price_logger`           | Base          | Logs prices; no trading (useful for data collection). |

Strategies receive the same merged state and portfolio view; the composite collects all intents and tags them with the strategy name for logging and broker handling.

---

## Configuration

- **`src/config/live_config.json`** — NBA: `system` (e.g. `max_workers`, `log_level`), `trading.mode` (`dry_run` | `live`), `trading.active_strategies`.
- **`src/config/nfl_live_config.json`** — NFL: same structure, `system.sport: "nfl"`.
- **`.env`** — Used by Kalshi auth; must include `KALSHI_API_KEY_ID`.
- **`kalshi_private_key.pem`** — Project root; PEM private key for Kalshi API signing.

Workers read the appropriate config to decide dry run vs live and which strategies to load.

---

## Setup

1. **Python** — Use a environment that matches the project (e.g. 3.10+).
2. **Dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   Key deps: `requests`, `websockets`, `cryptography`, `python-dotenv`, `Flask`, `nba_api`, `pandas`, `numpy`.
3. **Kalshi**
   - Create `.env` with `KALSHI_API_KEY_ID=...`.
   - Place `kalshi_private_key.pem` at the project root.
4. **Optional** — Ensure `src/storage/jobs`, `src/storage/kalshi/merged/states`, and `src/storage/kalshi/merged/nfl_states` exist (usually created by discovery and workers).

---

## Running

- **Daily cycle (discovery + workers)**  
  From project root:
  ```bash
  python -m src.automation.manager [--date YYYY-MM-DD] [--live]
  ```
  Uses `--date` or today (Eastern). Discovers NBA and NFL games, saves jobs, spawns one worker per game. Workers sleep until tipoff/kickoff minus N minutes, then run until game final and/or markets closed. `--live` does not change worker mode; workers use their config file for dry_run vs live.

- **Single NBA game worker (manual)**  
  ```bash
  python -m src.automation.game_worker --event-ticker KXNBAGAME-25NOV22LALBOS --game-id 0022500123 --home BOS --away LAL --date 2025-11-22 --markets TICKER1,TICKER2
  ```

- **Single NFL game worker (manual)**  
  ```bash
  python -m src.automation.nfl.game_worker --event-ticker ... --game-id ... --home NYG --away PHI --date 2025-11-23 --markets T1,T2
  ```

- **Backtest API**  
  ```bash
  python -m src.app.main
  ```
  Then:
  ```http
  POST /backtests
  Content-Type: application/json

  {
    "strategy": "late_game_underdog",
    "params": { "stake": 100, "max_price": 0.18, ... },
    "config": { "sport": "nba" }
  }
  ```
  Optional `config.game_ids` limits replay to those games; otherwise all state files in the sport’s merged directory are used. Response includes `run_id`, `summary`, `num_trades`; full run is under `src/storage/backtest_runs/<sport>/<strategy_name>/<run_id>/`.

---

## Project Layout (summary)

```
LiveEngine/
├── src/
│   ├── app/                 # Flask app; backtest POST endpoint
│   ├── automation/          # Discovery + game workers (NBA + NFL)
│   ├── config/              # live_config.json, nfl_live_config.json
│   ├── connectors/
│   │   ├── kalshi/          # Auth, HTTP client, ticker stream, state builder, NBA/NFL mergers
│   │   ├── nba/             # NBA scoreboard client
│   │   └── nfl/             # NFL scoreboard client
│   ├── core/                # Models, portfolio, execution, metrics, backtest loop, trade logger
│   ├── engine/              # LiveEngine, Broker (Mock + Kalshi)
│   ├── storage/             # Jobs, merged states, backtest runs, state writer, load_states
│   └── strategies/         # Base, composite, registry; mean_reversion, momentum, situational
├── requirements.txt
├── .env                     # KALSHI_API_KEY_ID (not committed)
├── kalshi_private_key.pem   # Kalshi API key (not committed)
└── README.md
```

---

## Safety and Limits

- **KalshiBroker** enforces a hard per-order cap (e.g. `MAX_ORDER_VALUE_SAFETY_CAP`) and balance check before live buys.
- Dry run is the default in config; set `trading.mode` to `"live"` only when intentionally trading with real funds.
- Workers and the engine do not auto-close positions; strategies emit open/close intents and the broker executes them.

---

## Summary

LiveEngine is a modular, sport-agnostic core (state stream → strategy → broker) with NBA and NFL-specific discovery, score feeds, and state mergers. It records merged state for backtests and runs strategies live against Kalshi with configurable dry-run vs live execution and a clear separation between automation, engine, and strategies.
