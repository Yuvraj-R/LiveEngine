# src/core/metrics.py

from typing import List, Dict, Any


def compute_metrics(cash, equity_curve: List[Dict[str, Any]], trades: List[Any]) -> Dict[str, Any]:
    if not equity_curve:
        return {
            "total_pnl": 0.0,
            "gross_pnl": 0.0,
            "total_fees": 0.0,
            "max_drawdown": 0.0,
            "num_trades": 0,
            "num_round_trips": 0,
            "num_closing_trades": 0,
            "hit_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "avg_fee_per_round_trip": 0.0,
            "buckets": {},
        }

    initial = equity_curve[0]["equity"]
    final = equity_curve[-1]["equity"]
    total_pnl = final - initial
    max_drawdown = _max_drawdown([p["equity"] for p in equity_curve])

    # Round trips (open → close/auto_close)
    open_by_market = {}
    round_trips = []

    for t in trades:
        action = getattr(t, "action", None)
        market_id = getattr(t, "market_id", None)

        if action == "open":
            open_by_market[market_id] = t

        elif action in ("close", "auto_close") and market_id in open_by_market:
            open_t = open_by_market.pop(market_id)

            entry_price = getattr(open_t, "price", None)
            exit_price = getattr(t, "price", None)
            pnl = getattr(t, "pnl", 0.0)

            # contracts should be identical on open/close
            contracts = getattr(open_t, "contracts", None)
            if contracts is None:
                contracts = getattr(t, "contracts", 0.0)

            # Theoretical PnL without fees vs realized PnL → infer total fees
            if (
                contracts is not None
                and entry_price is not None
                and exit_price is not None
            ):
                gross_pnl_rt = contracts * (exit_price - entry_price)
                fees_rt = gross_pnl_rt - pnl
            else:
                gross_pnl_rt = pnl
                fees_rt = 0.0

            round_trips.append(
                {
                    "market_id": market_id,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "contracts": contracts,
                    "pnl": pnl,        # net of fees
                    "fees": fees_rt,   # inferred total fees (open + close)
                    "gross_pnl": gross_pnl_rt,
                }
            )

    wins = []
    losses = []
    total_fees = 0.0
    gross_pnl_sum = 0.0

    buckets = {
        "0-0.05": [],
        "0.05-0.10": [],
        "0.10-0.15": [],
        "0.15+": [],
    }

    for rt in round_trips:
        pnl = rt["pnl"]
        fees_rt = rt["fees"]
        entry_price = rt["entry_price"]

        total_fees += fees_rt
        gross_pnl_sum += rt["gross_pnl"]

        if pnl > 0:
            wins.append(pnl)
        elif pnl < 0:
            losses.append(pnl)

        if entry_price is not None:
            if entry_price < 0.05:
                buckets["0-0.05"].append(rt)
            elif entry_price < 0.10:
                buckets["0.05-0.10"].append(rt)
            elif entry_price < 0.15:
                buckets["0.10-0.15"].append(rt)
            else:
                buckets["0.15+"].append(rt)

    num_round_trips = len(round_trips)
    num_closes = num_round_trips
    hit_rate = (len(wins) / num_closes) if num_closes else 0.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    avg_fee_per_round_trip = (
        total_fees / num_round_trips) if num_round_trips else 0.0

    gross_pnl = total_pnl + total_fees  # net + fees = theoretical gross

    bucket_stats = {}
    for name, arr in buckets.items():
        if arr:
            pnls = [x["pnl"] for x in arr]
            fees_arr = [x["fees"] for x in arr]

            wins_b = [x for x in pnls if x > 0]
            losses_b = [x for x in pnls if x < 0]

            total = len(arr)
            total_fees_b = sum(fees_arr)

            bucket_stats[name] = {
                "count": total,
                "hit_rate": len(wins_b) / total if total else 0.0,
                "avg_pnl": sum(pnls) / total if total else 0.0,
                "avg_win": (sum(wins_b) / len(wins_b)) if wins_b else 0.0,
                "avg_loss": (sum(losses_b) / len(losses_b)) if losses_b else 0.0,
                "total_fees": total_fees_b,
                "avg_fee": (total_fees_b / total) if total else 0.0,
            }
        else:
            bucket_stats[name] = {
                "count": 0,
                "hit_rate": 0.0,
                "avg_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "total_fees": 0.0,
                "avg_fee": 0.0,
            }

    return {
        "total_pnl": total_pnl,   # net of fees
        "gross_pnl": gross_pnl,   # before fees
        "total_fees": total_fees,
        "max_drawdown": max_drawdown,
        "num_trades": len(trades),
        "num_round_trips": num_round_trips,
        "num_closing_trades": num_closes,
        "hit_rate": hit_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_fee_per_round_trip": avg_fee_per_round_trip,
        "buckets": bucket_stats,
    }


def _max_drawdown(values: List[float]) -> float:
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    return max_dd
