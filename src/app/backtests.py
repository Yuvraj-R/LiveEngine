# src/app/backtests.py

from pathlib import Path
import datetime as dt
import json
import csv

from flask import Blueprint, request, jsonify

from src.core.backtest import run_backtest
from src.strategies import (
    LateGameUnderdogStrategy,
    TightGameCoinflipStrategy,
    NoScoreSpikeRevertStrategy,
    MicroMomentumFollowStrategy,
    PanicSpreadFadeStrategy,
    LateGameShockFadeStrategy,
    PriceShockMomentumStrategy,
    UnderdogResilienceStrategy,
    DeficitRecoveryStrategy,
    VolatileUnderdogExitStrategy,
)

bp = Blueprint("backtests", __name__)

STRATEGY_REGISTRY = {
    "late_game_underdog": LateGameUnderdogStrategy,
    "tight_game_coinflip": TightGameCoinflipStrategy,
    "no_score_spike_revert": NoScoreSpikeRevertStrategy,
    "micro_momentum_follow": MicroMomentumFollowStrategy,
    "panic_spread_fade": PanicSpreadFadeStrategy,
    "late_game_shock_fade": LateGameShockFadeStrategy,
    "price_shock_momentum": PriceShockMomentumStrategy,
    "underdog_resilience": UnderdogResilienceStrategy,
    "deficit_recovery": DeficitRecoveryStrategy,
    "volatile_underdog_exit": VolatileUnderdogExitStrategy,
}


def _save_backtest_run(
    strategy_name: str,
    config: dict,
    result,
    sport: str  # <--- CHANGED: Added sport arg
) -> str:
    """
    Persist a single backtest run under:

      src/storage/backtest_runs/<sport>/<strategy_name>/<run_id>/

    Files:
      - summary.json        (metrics)
      - config.json         (what was run)
      - trades.csv          (full trade log)
      - equity_curve.csv    (timestamp, equity)
    """

    # <--- CHANGED: Added sport to path
    base_dir = Path("src/storage/backtest_runs") / sport / strategy_name
    base_dir.mkdir(parents=True, exist_ok=True)

    # Run ID: UTC timestamp, filesystem-safe (no colons)
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1) summary.json
    summary_path = run_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(result.summary, f, indent=2)

    # 2) config.json
    config_path = run_dir / "config.json"
    with open(config_path, "w") as f:
        json.dump(config or {}, f, indent=2)

    # 3) trades.csv
    trades_path = run_dir / "trades.csv"
    with open(trades_path, "w", newline="") as f:
        fieldnames = ["timestamp", "market_id",
                      "action", "price", "contracts", "pnl"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in result.trades:
            writer.writerow({
                "timestamp": t.timestamp,
                "market_id": t.market_id,
                "action": t.action,
                "price": t.price,
                "contracts": t.contracts,
                "pnl": t.pnl,
            })

    # 4) equity_curve.csv
    equity_path = run_dir / "equity_curve.csv"
    equity_curve_min = _downsample_equity_curve_to_minutes(result.equity_curve)

    with open(equity_path, "w", newline="") as f:
        if equity_curve_min:
            fieldnames = list(equity_curve_min[0].keys())
        else:
            fieldnames = ["timestamp", "equity"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in equity_curve_min:
            writer.writerow(row)

    return run_id


def _downsample_equity_curve_to_minutes(equity_curve):
    """
    Collapse equity_curve to one row per minute (last seen in that minute).
    """
    by_minute = {}

    for row in equity_curve:
        ts = row.get("timestamp")
        if not ts:
            continue
        try:
            # handle both ...+00:00 and ...Z
            if ts.endswith("Z"):
                ts_dt = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                ts_dt = dt.datetime.fromisoformat(ts)
        except Exception:
            continue

        key = ts_dt.replace(second=0, microsecond=0)
        # keep the last seen row in that minute
        r = dict(row)
        r["timestamp"] = key.isoformat()
        by_minute[key] = r

    return [by_minute[k] for k in sorted(by_minute.keys())]


@bp.route("/backtests", methods=["POST"])
def create_backtest():
    data = request.json or {}

    strategy_name = data.get("strategy")
    params = data.get("params", {})
    config = data.get("config", {})

    # <--- CHANGED: Extract sport
    sport = config.get("sport", "nba").lower()

    StrategyClass = STRATEGY_REGISTRY.get(strategy_name)
    if not StrategyClass:
        return jsonify({"error": "unknown strategy"}), 400

    strategy = StrategyClass(params)
    result = run_backtest(strategy, config)

    # Persist full run to disk
    # <--- CHANGED: Pass sport
    run_id = _save_backtest_run(strategy_name, config, result, sport)

    # Return only light summary + metadata
    response = {
        "strategy": strategy_name,
        "run_id": run_id,
        "sport": sport,  # <--- Added for clarity
        "summary": result.summary,
        "num_trades": len(result.trades),
    }

    return jsonify(response)
