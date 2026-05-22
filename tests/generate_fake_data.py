"""
generate_fake_data.py — Tạo fake CSV data cho tests.

Usage:
    python tests/generate_fake_data.py [--dir /tmp/btc_fake_test]

Files tạo ra:
    klines_1s.csv      — 1s OHLCV, 3 giờ gần nhất (10800 rows)
    liquidations.csv   — BTCUSDT + vài coin khác
    orderbook.csv      — 1 snapshot (dùng cho patch)
    features_5m.csv    — 120 rows features_1m format (tên cũ dùng trong tests)
    paper_trades.csv   — WIN, LOSS, EXPIRED, UNFILLED + 1 OPEN trade
"""

import argparse
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path


BASE_PRICE = 80_000.0


def generate(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)

    _write_klines(out_dir, now)
    _write_liquidations(out_dir, now)
    _write_orderbook(out_dir, now)
    _write_features(out_dir, now)
    _write_trades(out_dir, now)

    print(f"[gen] Fake data → {out_dir}")
    print(f"  klines_1s.csv:   10800 rows (3h × 1s)")
    print(f"  liquidations.csv: 21 rows (20 BTCUSDT + 1 ETHUSDT)")
    print(f"  orderbook.csv:    1 row")
    print(f"  features_5m.csv: 120 rows (2h × 1m)")
    print(f"  paper_trades.csv: 5 rows (WIN, LOSS, EXPIRED, UNFILLED, OPEN)")


def _write_klines(out_dir: Path, now: datetime) -> None:
    path = out_dir / "klines_1s.csv"
    n = 10_800  # 3 hours
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "open", "high", "low", "close",
                    "volume", "taker_buy_vol", "num_trades"])
        for i in range(n):
            ts = now - timedelta(seconds=n - i)
            price = BASE_PRICE + (i % 200) * 0.5 - 50.0
            o = round(price, 2)
            h = round(price + 5.0, 2)
            lo = round(price - 5.0, 2)
            c = round(price + 1.0, 2)
            w.writerow([ts.isoformat(), o, h, lo, c, 10.0, 5.5, 120])


def _write_liquidations(out_dir: Path, now: datetime) -> None:
    path = out_dir / "liquidations.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_time", "symbol", "side", "price", "qty", "usd_value"])
        for i in range(20):
            ts = now - timedelta(minutes=60 - i * 3)
            side = "BUY" if i % 2 == 0 else "SELL"
            w.writerow([ts.isoformat(), "BTCUSDT", side,
                        BASE_PRICE, 0.1, 8_000.0])
        # Non-BTCUSDT entry — deve ser filtrada por load_liquidations
        ts = now - timedelta(minutes=1)
        w.writerow([ts.isoformat(), "ETHUSDT", "BUY", 3000.0, 1.0, 3_000.0])


def _write_orderbook(out_dir: Path, now: datetime) -> None:
    path = out_dir / "orderbook.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp",
                    "bid1_price", "bid1_qty", "ask1_price", "ask1_qty",
                    "mid_price", "spread", "bid_vol_total", "ask_vol_total", "imbalance"])
        ts = now - timedelta(seconds=5)
        w.writerow([ts.isoformat(),
                    BASE_PRICE - 1, 5.0, BASE_PRICE + 1, 3.0,
                    BASE_PRICE, 2.0, 5.0, 3.0, 0.625])


_FEAT_COLS = [
    "timestamp", "current_price",
    "price_change_1m", "price_change_30s", "volatility_1m", "volume_1m", "taker_buy_ratio",
    "liq_long_usd_1m", "liq_short_usd_1m", "liq_total_1m", "liq_ratio_1m", "liq_accel_30s",
    "imbalance_now", "imbalance_avg_1m", "imbalance_trend",
    "spread_now", "bid_vol_now", "ask_vol_now", "wall_ratio", "mid_price_now",
    "cvd_delta_1m", "cvd_delta_30s",
    "whale_buy_count", "whale_sell_count", "whale_net",
    "whale_buy_usd_1m", "whale_sell_usd_1m", "whale_dominance",
    "oi_now", "oi_usd_now",
    "delta_oi_1m", "delta_oi_30m", "delta_oi_1h", "oi_acceleration",
    "funding_rate", "funding_rate_abs", "funding_bias",
    "funding_long_heavy", "funding_short_heavy",
    "funding_rate_change", "funding_trend_3h",
    "secs_to_next_funding", "funding_urgency",
    "spot_cvd_delta_1m", "spot_cvd_delta_30s",
    "basis_pct", "basis_change_1m", "basis_positive",
    "cvd_divergence",
    # Label columns
    "cascade_long_1m", "cascade_long_2m", "cascade_long_3m",
    "cascade_short_1m", "cascade_short_2m", "cascade_short_3m",
    "time_to_cascade_long", "time_to_cascade_short",
]


def _write_features(out_dir: Path, now: datetime) -> None:
    path = out_dir / "features_5m.csv"
    n = 120  # 2 hours of 1-min rows
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_FEAT_COLS)
        w.writeheader()
        for i in range(n):
            ts = now - timedelta(minutes=n - i)
            price = round(BASE_PRICE + i * 0.1, 2)
            row = {col: "" for col in _FEAT_COLS}
            row.update({
                "timestamp":         ts.isoformat(),
                "current_price":     price,
                "price_change_1m":   0.001,
                "price_change_30s":  0.0005,
                "volatility_1m":     0.0002,
                "volume_1m":         100.0,
                "taker_buy_ratio":   0.55,
                "liq_long_usd_1m":   600_000.0,
                "liq_short_usd_1m":  1_000_000.0,
                "liq_total_1m":      1_600_000.0,
                "liq_ratio_1m":      0.6,
                "liq_accel_30s":     0.5,
                "imbalance_now":     0.62,
                "imbalance_avg_1m":  0.58,
                "imbalance_trend":   0.04,
                "spread_now":        2.0,
                "bid_vol_now":       5.0,
                "ask_vol_now":       3.0,
                "wall_ratio":        1.5,
                "mid_price_now":     price,
                "cvd_delta_1m":      120.0,
                "cvd_delta_30s":     60.0,
                "whale_buy_count":   5,
                "whale_sell_count":  3,
                "whale_net":         2,
                "whale_buy_usd_1m":  500_000.0,
                "whale_sell_usd_1m": 300_000.0,
                "whale_dominance":   0.6,
                "oi_now":            100_000.0,
                "oi_usd_now":        8_000_000_000.0,
                "delta_oi_1m":       200.0,
                "delta_oi_30m":      500.0,
                "delta_oi_1h":       1_000.0,
                "oi_acceleration":   10.0,
                "funding_rate":      0.0001,
                "funding_rate_abs":  0.0001,
                "funding_bias":      1.0,
                "funding_long_heavy":  "True",
                "funding_short_heavy": "False",
                "funding_rate_change": 0.00001,
                "funding_trend_3h":    0.001,
                "secs_to_next_funding": 14_400,
                "funding_urgency":     0.5,
                "spot_cvd_delta_1m":   90.0,
                "spot_cvd_delta_30s":  45.0,
                "basis_pct":           0.001,
                "basis_change_1m":     0.0001,
                "basis_positive":      "True",
                "cvd_divergence":      30.0,
            })
            # Label rows except last 5 (those are "unlabeled" / pending)
            if i < n - 5:
                row["cascade_long_1m"]  = 0
                row["cascade_long_2m"]  = 0
                row["cascade_long_3m"]  = 1 if i % 20 == 0 else 0
                row["cascade_short_1m"] = 0
                row["cascade_short_2m"] = 0
                row["cascade_short_3m"] = 1 if i % 15 == 0 else 0
                row["time_to_cascade_long"]  = 3 if i % 20 == 0 else ""
                row["time_to_cascade_short"] = 3 if i % 15 == 0 else ""
            w.writerow(row)


_TRADE_COLS = [
    "opened_at", "signal", "prob", "entry", "tp", "sl", "rr", "est_minutes",
    "order_type", "closed_at", "outcome", "pnl_pct", "hit_tp", "hit_sl",
]


def _write_trades(out_dir: Path, now: datetime) -> None:
    path = out_dir / "paper_trades.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_TRADE_COLS)
        w.writeheader()

        # WIN
        w.writerow({
            "opened_at": (now - timedelta(hours=2)).isoformat(),
            "signal": "CASCADE_LONG", "prob": 0.85,
            "entry": 79_000, "tp": 79_095, "sl": 78_905, "rr": 1.0, "est_minutes": 1.0,
            "order_type": "market",
            "closed_at": (now - timedelta(hours=2) + timedelta(minutes=3)).isoformat(),
            "outcome": "WIN", "pnl_pct": 0.12, "hit_tp": 1, "hit_sl": 0,
        })
        # LOSS
        w.writerow({
            "opened_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
            "signal": "CASCADE_SHORT", "prob": 0.75,
            "entry": 80_000, "tp": 79_904, "sl": 80_096, "rr": 1.0, "est_minutes": 2.0,
            "order_type": "market",
            "closed_at": (now - timedelta(hours=1, minutes=27)).isoformat(),
            "outcome": "LOSS", "pnl_pct": -0.12, "hit_tp": 0, "hit_sl": 1,
        })
        # EXPIRED
        w.writerow({
            "opened_at": (now - timedelta(hours=1)).isoformat(),
            "signal": "CASCADE_LONG", "prob": 0.72,
            "entry": 79_500, "tp": 79_595, "sl": 79_405, "rr": 1.0, "est_minutes": 3.0,
            "order_type": "maker",
            "closed_at": (now - timedelta(hours=1) + timedelta(minutes=3)).isoformat(),
            "outcome": "EXPIRED", "pnl_pct": -0.05, "hit_tp": 0, "hit_sl": 0,
        })
        # UNFILLED
        w.writerow({
            "opened_at": (now - timedelta(minutes=30)).isoformat(),
            "signal": "CASCADE_SHORT", "prob": 0.68,
            "entry": 80_100, "tp": 80_004, "sl": 80_196, "rr": 1.0, "est_minutes": 1.0,
            "order_type": "maker",
            "closed_at": (now - timedelta(minutes=29, seconds=30)).isoformat(),
            "outcome": "UNFILLED", "pnl_pct": 0.0, "hit_tp": 0, "hit_sl": 0,
        })
        # OPEN (pending) — within 30 minutes so read_active_signal() picks it up
        w.writerow({
            "opened_at": (now - timedelta(minutes=5)).isoformat(),
            "signal": "CASCADE_LONG", "prob": 0.80,
            "entry": 80_000, "tp": 80_096, "sl": 79_904, "rr": 1.0, "est_minutes": 1.0,
            "order_type": "maker",
            "closed_at": "", "outcome": "", "pnl_pct": "", "hit_tp": "", "hit_sl": "",
        })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate fake CSV test data")
    parser.add_argument("--dir", default="/tmp/btc_fake_test",
                        help="Output directory (default: /tmp/btc_fake_test)")
    args = parser.parse_args()
    generate(Path(args.dir))
