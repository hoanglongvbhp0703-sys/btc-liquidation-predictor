#!/usr/bin/env python3
"""
generate_fake_data.py — Sinh dữ liệu demo đầy đủ cho BTC Liquidation Dashboard.

Tạo 5 giờ dữ liệu tính đến NOW với:
  - Nến 1m đẹp (OHLC thật, body rõ ràng, wick hợp lý)
  - Nến 1s expand từ 1m để nhất quán
  - Liquidation events ít nhưng có ý nghĩa (size marker to)
  - Features 5m coherent (imbalance/CVD theo hướng giá)
  - Model XGBoost được train thật → prob hiển thị trên dashboard
  - Paper trades khớp với vùng giá thực tế

Usage:
    python tests/generate_fake_data.py           # ghi vào data/ + train model
    python tests/generate_fake_data.py --dry-run
    python scripts/generate_fake_data.py --dir /tmp/fake_data --no-model
"""

import argparse
import csv
import json
import math
import pickle
import random
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT_DIR      = Path(__file__).parent.parent
DATA_DIR      = ROOT_DIR / "data" / "raw"         # raw CSVs (klines, liq...)
PROCESSED_DIR = ROOT_DIR / "data" / "processed"   # features, paper_trades
MODEL_DIR     = ROOT_DIR / "ml" / "artifacts"

# ── Scenario ───────────────────────────────────────────────────────────────
BASE_PRICE   = 84_000.0
HOURS        = 5.0            # giờ data sinh ra
SEED         = 7

LIQ_UPPER    = 85_900.0       # vùng thanh lý trên (~2.3% trên base)
LIQ_LOWER    = 82_100.0       # vùng thanh lý dưới (~2.3% dưới base)

random.seed(SEED)

FEATURE_COLS = [
    "price_change_5m", "price_change_1m", "volatility_5m",
    "volume_5m", "taker_buy_ratio",
    "liq_long_usd_5m", "liq_short_usd_5m", "liq_total_5m", "liq_ratio_5m",
    "dist_to_upper", "dist_to_lower",
    "imbalance_now", "imbalance_avg_1m", "imbalance_trend",
    "spread_now", "bid_vol_now", "ask_vol_now", "wall_ratio",
    "cvd_delta_5m", "cvd_delta_1m",
    "whale_buy_count", "whale_sell_count", "whale_net",
    "whale_buy_usd_5m", "whale_sell_usd_5m", "whale_dominance",
    "delta_oi_5m", "delta_oi_30m", "delta_oi_1h", "oi_acceleration",
    "funding_rate", "funding_rate_abs", "funding_bias",
    "funding_long_heavy", "funding_short_heavy",
    "funding_rate_change", "funding_trend_3h",
    "secs_to_next_funding", "funding_urgency",
]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run",  action="store_true")
    p.add_argument("--no-model", action="store_true", help="Bỏ qua bước train model")
    p.add_argument("--dir",      default=None)
    p.add_argument("--hours",    type=float, default=None, help="Override HOURS constant")
    p.add_argument("--features-only", action="store_true", help="Chỉ sinh features_5m.csv (không klines_1s, liq...)")
    return p.parse_args()


# ══════════════════════════════════════════════════════════════════════════════
# 1. Price simulation — sinh 1m candles đẹp trước, rồi expand xuống 1s
# ══════════════════════════════════════════════════════════════════════════════

def simulate_1m_candles(n_minutes: int, base: float) -> list[dict]:
    """
    Sinh n_minutes nến 1m với OHLC thực tế:
    - open = close của nến trước (liên tục)
    - body ~ 0.06-0.15% của giá
    - wick ~ 20-50% body, random up/down
    - trend mean-reverting để giá không drift quá xa
    """
    candles = []
    price   = base
    trend   = 0.0       # momentum hiện tại

    # Tạo "session phases" để chart trông tự nhiên hơn
    phases = _build_phases(n_minutes)

    for i in range(n_minutes):
        phase_bias = phases[i]

        # Trend mean-reverting + phase bias
        trend = trend * 0.88 + random.gauss(phase_bias, 0.00015)
        trend = max(-0.0035, min(0.0035, trend))

        open_ = round(price, 2)

        # Body size: lognormal, bình thường ~$40-120
        body_pct = abs(random.gauss(0, 0.0009)) + 0.0001
        direction = 1 if (trend + random.gauss(0, 0.0005)) > 0 else -1
        close = round(open_ * (1 + direction * body_pct), 2)

        body_hi = max(open_, close)
        body_lo = min(open_, close)
        body_sz = body_hi - body_lo

        # Wick: nhỏ hơn body, random
        wick_up = abs(random.gauss(0, 0.35)) * body_sz + body_sz * 0.05
        wick_dn = abs(random.gauss(0, 0.35)) * body_sz + body_sz * 0.05

        high = round(body_hi + wick_up, 2)
        low  = round(body_lo - wick_dn, 2)

        # Clamp vào vùng liq zones để trông có ý nghĩa
        high = min(high, LIQ_UPPER * 1.005)
        low  = max(low,  LIQ_LOWER * 0.995)
        low  = min(low, open_, close)      # low không vượt body
        high = max(high, open_, close)

        vol = abs(random.gauss(18, 10))  # BTC volume per minute

        candles.append({
            "open":   open_,
            "high":   high,
            "low":    low,
            "close":  close,
            "volume": round(vol, 3),
        })
        price = close

    return candles


def _build_phases(n: int) -> list[float]:
    """Tạo chuỗi phase bias (up/down/sideways) cho chart trông tự nhiên."""
    phases = [0.0] * n
    segs = [
        (0.15, +0.00015),   # 15% đầu: nhẹ lên
        (0.20, -0.00008),   # 20%: sideways nhẹ xuống
        (0.25, +0.00020),   # 25%: uptrend
        (0.20, -0.00015),   # 20%: pullback
        (0.20, +0.00005),   # 20% cuối: recovery nhẹ
    ]
    pos = 0
    for frac, bias in segs:
        end = min(n, pos + int(n * frac))
        for j in range(pos, end):
            phases[j] = bias
        pos = end
    return phases


def expand_to_1s(candle: dict, ts_start: datetime) -> list[dict]:
    """
    Mở rộng 1 nến 1m thành 60 nến 1s, giá nằm trong [low, high] của nến 1m.
    Open của 1s đầu = open của 1m. Close của 1s cuối = close của 1m.
    """
    o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]
    vol_total   = candle["volume"]

    # Tạo price path trong nến: brownian bridge từ open → close
    prices = _brownian_bridge(o, c, 60, sigma=(h - l) * 0.08)
    prices = [max(l, min(h, p)) for p in prices]
    prices[-1] = c   # đảm bảo close khớp

    rows = []
    vols = _split_volume(vol_total, 60)

    for i in range(60):
        ts   = ts_start + timedelta(seconds=i)
        p    = round(prices[i], 2)
        p_prev = round(prices[i - 1], 2) if i > 0 else o

        # 1s candle: small body + tiny wick
        s_open  = p_prev
        s_close = p
        s_high  = round(max(p_prev, p) + abs(random.gauss(0, (h - l) * 0.015)), 2)
        s_low   = round(min(p_prev, p) - abs(random.gauss(0, (h - l) * 0.015)), 2)
        s_high  = min(s_high, h)
        s_low   = max(s_low,  l)

        tbv = round(vols[i] * random.uniform(0.3, 0.7), 3)

        rows.append({
            "open_time":     ts.isoformat(),
            "open":          s_open,
            "high":          s_high,
            "low":           s_low,
            "close":         s_close,
            "volume":        round(vols[i], 3),
            "taker_buy_vol": tbv,
            "num_trades":    random.randint(8, 80),
        })

    return rows


def _brownian_bridge(start: float, end: float, n: int, sigma: float) -> list[float]:
    """Brownian bridge: path từ start → end trong n bước."""
    path = [start]
    for i in range(1, n):
        remaining = n - i
        t_frac    = i / n
        target    = start + (end - start) * t_frac
        drift     = (end - path[-1]) / remaining
        noise     = random.gauss(0, sigma)
        path.append(path[-1] + drift + noise)
    path.append(end)
    return path[:n]


def _split_volume(total: float, n: int) -> list[float]:
    """Chia volume tổng thành n phần ngẫu nhiên theo Dirichlet-like."""
    weights = [abs(random.gauss(1, 0.5)) for _ in range(n)]
    s = sum(weights)
    return [total * w / s for w in weights]


# ══════════════════════════════════════════════════════════════════════════════
# 2. Data generators
# ══════════════════════════════════════════════════════════════════════════════

def gen_klines_1s(candles_1m: list[dict], t0: datetime) -> list[dict]:
    """Expand danh sách nến 1m thành 1s rows."""
    rows = []
    for i, c in enumerate(candles_1m):
        rows.extend(expand_to_1s(c, t0 + timedelta(minutes=i)))
    return rows


def gen_liquidations(candles_1m: list[dict], t0: datetime) -> list[dict]:
    """
    Liquidation events thực tế:
    - BTCUSDT: ~8-12 sự kiện lớn ($100k-$3M), cluster gần high/low của nến
    - Other symbols: rải rác, giá trị nhỏ hơn
    """
    rows = []

    # BTCUSDT liquidations — ít nhưng lớn
    btc_events = []
    n = len(candles_1m)
    for i, c in enumerate(candles_1m):
        # Chỉ tạo liquidation khi nến có body lớn (biến động mạnh)
        body = abs(c["close"] - c["open"])
        if body < 50:
            continue
        if random.random() > 0.12:   # ~12% nến có liquidation BTCUSDT
            continue

        ts = (t0 + timedelta(minutes=i, seconds=random.randint(5, 55))).isoformat()
        # Long liquidations khi giá xuống → price gần low, side=BUY (forced buy to close)
        # Short liquidations khi giá lên → price gần high, side=SELL
        if c["close"] < c["open"]:
            side  = "BUY"
            price = round(c["low"] + random.uniform(0, (c["open"] - c["low"]) * 0.3), 1)
        else:
            side  = "SELL"
            price = round(c["high"] - random.uniform(0, (c["high"] - c["close"]) * 0.3), 1)

        qty       = round(random.uniform(1.5, 35), 3)   # BTC qty lớn để marker to
        usd_value = round(price * qty, 2)

        rows.append({
            "event_time": ts,
            "symbol":     "BTCUSDT",
            "side":       side,
            "price":      price,
            "qty":        qty,
            "usd_value":  usd_value,
        })

    # Other coins — rải đều, nhỏ hơn
    other_symbols = [
        ("ETHUSDT", 2500, 50),
        ("SOLUSDT", 150, 200),
        ("BNBUSDT", 600, 80),
        ("XRPUSDT", 0.6, 5000),
        ("DOGEUSDT", 0.15, 20000),
    ]
    for i in range(n):
        if random.random() > 0.08:
            continue
        sym, price_base, qty_base = random.choice(other_symbols)
        ts    = (t0 + timedelta(minutes=i, seconds=random.randint(0, 59))).isoformat()
        price = round(price_base * random.uniform(0.97, 1.03), 4)
        qty   = round(abs(random.gauss(qty_base, qty_base * 0.5)), 1)
        rows.append({
            "event_time": ts,
            "symbol":     sym,
            "side":       random.choice(["BUY", "SELL"]),
            "price":      price,
            "qty":        qty,
            "usd_value":  round(price * qty, 2),
        })

    rows.sort(key=lambda r: r["event_time"])
    return rows


def gen_orderbook(candles_1m: list[dict], t0: datetime) -> list[dict]:
    """Snapshot orderbook mỗi 1s, imbalance tương quan với hướng giá."""
    rows = []
    n = len(candles_1m)

    for i, c in enumerate(candles_1m):
        # imbalance > 0.5 khi nến lên, < 0.5 khi nến xuống
        bullish = c["close"] > c["open"]
        base_imb = random.gauss(0.58 if bullish else 0.42, 0.06)
        base_imb = max(0.15, min(0.85, base_imb))

        mid = (c["open"] + c["close"]) / 2

        for s in range(60):
            ts  = (t0 + timedelta(minutes=i, seconds=s)).isoformat()
            imb = max(0.1, min(0.9, base_imb + random.gauss(0, 0.03)))
            bid_vol = round(abs(random.gauss(12, 5)), 3)
            ask_vol = round(abs(random.gauss(12, 5)), 3)
            spread  = round(random.uniform(0.1, 0.5), 2)

            row = {"timestamp": ts}
            for j in range(1, 6):
                row[f"bid{j}_price"] = round(mid - spread * j, 2)
                row[f"bid{j}_qty"]   = round(abs(random.gauss(2, 1.5)), 3)
                row[f"ask{j}_price"] = round(mid + spread * j, 2)
                row[f"ask{j}_qty"]   = round(abs(random.gauss(2, 1.5)), 3)
            row["mid_price"]     = round(mid, 2)
            row["spread"]        = spread
            row["bid_vol_total"] = bid_vol
            row["ask_vol_total"] = ask_vol
            row["imbalance"]     = round(imb, 10)
            rows.append(row)

    return rows


def gen_aggtrades(candles_1m: list[dict], t0: datetime) -> list[dict]:
    """Aggregate trades, CVD theo hướng giá."""
    rows = []
    cvd = 0.0

    for i, c in enumerate(candles_1m):
        bullish = c["close"] > c["open"]
        for s in range(60):
            ts  = (t0 + timedelta(minutes=i, seconds=s)).isoformat()
            price = round(c["open"] + (c["close"] - c["open"]) * (s / 59), 2)
            qty   = round(abs(random.gauss(0.3, 0.4)), 3)
            # CVD tích lũy theo hướng nến
            maker = 0 if (bullish and random.random() < 0.6) else (5 if random.random() < 0.6 else 2)
            delta = qty if maker == 0 else -qty
            cvd   = round(cvd + delta, 3)
            rows.append({
                "timestamp":       ts,
                "agg_id":          "BATCH",
                "price":           price,
                "qty":             qty,
                "usd_value":       round(price * qty, 5),
                "is_buyer_maker":  maker,
                "cvd_delta":       round(delta, 3),
            })

    return rows


def gen_funding(n_minutes: int, t0: datetime) -> list[dict]:
    rows = []
    rate = random.gauss(0.00012, 0.00003)
    for i in range(0, n_minutes, 5):
        ts   = (t0 + timedelta(minutes=i)).isoformat()
        rate = round(rate + random.gauss(0, 0.000008), 8)
        next_fund = (t0 + timedelta(minutes=i) + timedelta(hours=8)).isoformat()
        rows.append({
            "timestamp":         ts,
            "funding_rate":      rate,
            "next_funding_time": next_fund,
        })
    return rows


def gen_open_interest(candles_1m: list[dict], t0: datetime) -> list[dict]:
    rows = []
    oi_btc = 115_000.0
    for i in range(0, len(candles_1m), 5):
        ts   = (t0 + timedelta(minutes=i)).isoformat()
        # OI tăng khi giá tăng (bullish)
        if i < len(candles_1m):
            bullish = candles_1m[i]["close"] > candles_1m[i]["open"]
            oi_btc += random.gauss(30 if bullish else -10, 40)
        oi_usd = round(oi_btc * BASE_PRICE, 2)
        rows.append({
            "timestamp": ts,
            "oi_btc":    round(oi_btc, 3),
            "oi_usd":    oi_usd,
        })
    return rows


def gen_features(candles_1m: list[dict], t0: datetime) -> list[dict]:
    """
    Features 5m: tổng hợp mỗi 5 nến 1m.
    Tất cả giá trị nhất quán với candle data thực tế.
    """
    rows = []
    n    = len(candles_1m)
    oi   = 115_000.0
    fund = 0.00012
    upper = LIQ_UPPER
    lower = LIQ_LOWER
    cvd_acc = 0.0

    i = 0
    while i < n:
        window = candles_1m[i: i + 5]
        if not window:
            break

        closes = [c["close"] for c in window]
        opens  = [c["open"]  for c in window]
        highs  = [c["high"]  for c in window]
        lows   = [c["low"]   for c in window]
        vols   = [c["volume"] for c in window]

        price     = closes[-1]
        price_5m_ago = opens[0]
        price_1m_ago = closes[-2] if len(closes) >= 2 else opens[-1]

        pc_5m = round((price - price_5m_ago) / price_5m_ago, 6)
        pc_1m = round((price - price_1m_ago) / price_1m_ago, 6)

        vol_5m = round(sum(vols), 4)
        vol_range = max(highs) - min(lows)
        volatility = round(vol_range, 4)

        # Imbalance correlated với direction
        bullish = price > price_5m_ago
        imb_now = round(max(0.15, min(0.85, random.gauss(0.57 if bullish else 0.43, 0.05))), 6)
        imb_avg = round(max(0.15, min(0.85, imb_now + random.gauss(0, 0.02))), 6)

        # CVD correlated với direction
        cvd_delta = round(random.gauss(120 if bullish else -80, 60), 4)
        cvd_acc  += cvd_delta
        cvd_1m    = round(cvd_delta / 5, 4)

        # OI
        oi      += random.gauss(20 if bullish else -10, 30)
        d_oi_5m  = round(random.gauss(0.0003 if bullish else -0.0002, 0.0003), 6)
        d_oi_30m = round(d_oi_5m * 5 + random.gauss(0, 0.0005), 6)
        d_oi_1h  = round(d_oi_30m * 1.5 + random.gauss(0, 0.0008), 6)

        # Funding
        fund = round(fund + random.gauss(0, 0.000005), 8)
        fund_bias = 1.0 if fund > 0 else -1.0
        secs_next = random.randint(1800, 28800)

        # Liq zones — luôn bám sát giá (1.5-2.5%) để label phân bố đều
        upper = round(price * (1.0 + random.uniform(0.015, 0.025)), 1)
        lower = round(price * (1.0 - random.uniform(0.015, 0.025)), 1)

        dist_up = round((upper - price) / price, 6)
        dist_lo = round((price - lower) / price, 6)

        # Liquidations trong 5m (giả lập)
        liq_long  = round(abs(random.gauss(8000, 6000)), 2)
        liq_short = round(abs(random.gauss(12000, 8000)), 2)
        liq_total = round(liq_long + liq_short, 2)
        liq_ratio = round(liq_short / liq_total if liq_total > 0 else 0.5, 6)

        # Whale
        w_buy  = random.randint(0, 6)
        w_sell = random.randint(0, 6)
        w_buy_usd  = round(abs(random.gauss(400_000, 200_000)), 2)
        w_sell_usd = round(abs(random.gauss(400_000, 200_000)), 2)
        w_dom = round(random.uniform(0.35, 0.75), 6)

        # Label: 1 nếu giá có khả năng chạm upper zone trong 30 phút tới
        # Heuristic: prob cao khi dist_up nhỏ + imbalance mua mạnh + cvd dương
        score = (1 - dist_up * 30) * 0.4 + (imb_now - 0.5) * 0.4 + (cvd_delta / 300) * 0.2
        label = 1 if score > 0.05 and random.random() < 0.45 else 0

        ts = (t0 + timedelta(minutes=i)).isoformat()

        rows.append({
            "timestamp":          ts,
            "current_price":      price,
            "price_change_5m":    pc_5m,
            "price_change_1m":    pc_1m,
            "volatility_5m":      volatility,
            "volume_5m":          vol_5m,
            "taker_buy_ratio":    round(random.uniform(0.35, 0.65), 6),
            "liq_long_usd_5m":    liq_long,
            "liq_short_usd_5m":   liq_short,
            "liq_total_5m":       liq_total,
            "liq_ratio_5m":       liq_ratio,
            "liq_zone_upper":     upper,
            "liq_zone_lower":     lower,
            "dist_to_upper":      dist_up,
            "dist_to_lower":      dist_lo,
            "imbalance_now":      imb_now,
            "imbalance_avg_1m":   imb_avg,
            "imbalance_trend":    round(imb_now - imb_avg, 6),
            "spread_now":         round(random.uniform(0.1, 0.4), 2),
            "bid_vol_now":        round(abs(random.gauss(12, 5)), 3),
            "ask_vol_now":        round(abs(random.gauss(12, 5)), 3),
            "wall_ratio":         round(random.uniform(0.25, 0.75), 6),
            "mid_price_now":      price,
            "cvd_delta_5m":       cvd_delta,
            "cvd_delta_1m":       cvd_1m,
            "whale_buy_count":    w_buy,
            "whale_sell_count":   w_sell,
            "whale_net":          w_buy - w_sell,
            "whale_buy_usd_5m":   w_buy_usd,
            "whale_sell_usd_5m":  w_sell_usd,
            "whale_dominance":    w_dom,
            "oi_now":             round(oi, 3),
            "oi_usd_now":         round(oi * price, 2),
            "delta_oi_5m":        d_oi_5m,
            "delta_oi_30m":       d_oi_30m,
            "delta_oi_1h":        d_oi_1h,
            "oi_acceleration":    round(random.gauss(0, 0.00003), 5),
            "funding_rate":       fund,
            "funding_rate_abs":   abs(fund),
            "funding_bias":       fund_bias,
            "funding_long_heavy": fund > 0,
            "funding_short_heavy": fund < 0,
            "funding_rate_change": round(random.gauss(0, 0.000006), 8),
            "funding_trend_3h":   round(random.gauss(0, 0.00002), 8),
            "secs_to_next_funding": secs_next,
            "funding_urgency":    round(1 - secs_next / 28800, 4),
            "label":              label,
        })

        i += 5

    return rows


def gen_trades(candles_1m: list[dict], t0: datetime, now: datetime) -> list[dict]:
    """
    Paper trades thực tế: entry/TP/SL dựa trên giá thực trong candles.
    5 trades đã đóng (mix WIN/LOSS) + 1 open trade trong 30 phút gần đây.
    """
    rows = []
    outcomes_plan = ["WIN", "WIN", "LOSS", "WIN", "LOSS", "WIN"]

    n = len(candles_1m)
    step = max(1, n // 8)  # mỗi ~1/8 thời gian có 1 trade

    for k, outcome in enumerate(outcomes_plan):
        idx   = min(k * step + random.randint(0, step // 2), n - 10)
        c     = candles_1m[idx]
        entry = round(c["close"], 0)

        # TP/SL theo % cố định → R:R luôn hợp lệ bất kể giá dịch chuyển
        tp = round(entry * 1.015, 0)   # +1.5%
        sl = round(entry * 0.990, 0)   # -1.0%
        rr = round((tp - entry) / (entry - sl), 2)

        opened = (t0 + timedelta(minutes=idx)).isoformat()
        closed = (t0 + timedelta(minutes=idx + random.randint(8, 25))).isoformat()
        pnl    = round((tp - entry) / entry * 100, 3) if outcome == "WIN" else round((sl - entry) / entry * 100, 3)
        prob   = round(random.uniform(0.68, 0.92), 4)

        rows.append({
            "opened_at":  opened,
            "signal":     "LONG",
            "prob":       prob,
            "entry":      entry,
            "tp":         tp,
            "sl":         sl,
            "rr":         rr,
            "closed_at":  closed,
            "outcome":    outcome,
            "pnl_pct":    pnl,
            "hit_tp":     outcome == "WIN",
            "hit_sl":     outcome == "LOSS",
        })

    # 1 open trade trong 20 phút gần nhất
    last_c = candles_1m[-20] if len(candles_1m) >= 20 else candles_1m[-1]
    entry  = round(last_c["close"], 0)
    tp     = round(entry * 1.015, 0)   # +1.5%
    sl     = round(entry * 0.990, 0)   # -1.0%
    rr     = round((tp - entry) / (entry - sl), 2)

    rows.append({
        "opened_at":  (now - timedelta(minutes=12)).isoformat(),
        "signal":     "LONG",
        "prob":       round(random.uniform(0.72, 0.90), 4),
        "entry":      entry,
        "tp":         tp,
        "sl":         sl,
        "rr":         rr,
        "closed_at":  "",
        "outcome":    "",
        "pnl_pct":    "",
        "hit_tp":     "",
        "hit_sl":     "",
    })

    return rows


# ══════════════════════════════════════════════════════════════════════════════
# 3. Model training
# ══════════════════════════════════════════════════════════════════════════════

def train_mock_model(features_file: Path, dry_run: bool):
    """Train LightGBM thật trên fake features → lưu vào model/saved/."""
    if dry_run:
        print("  [DRY]  model training — skipped")
        return

    print("  [MODEL] Training LightGBM on fake data...")
    import numpy as np
    import pandas as pd
    from lightgbm import LGBMClassifier, early_stopping, log_evaluation
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import roc_auc_score

    df = pd.read_csv(features_file)
    df["label"] = pd.to_numeric(df["label"], errors="coerce")
    df = df[df["label"].isin([0, 1])].copy()
    df["label"] = df["label"].astype(int)

    if len(df) < 50:
        print("  [MODEL] Không đủ data để train")
        return

    # Boolean → int
    for col in ("funding_long_heavy", "funding_short_heavy"):
        if col in df.columns:
            df[col] = df[col].astype(str).map(
                {"True": 1, "False": 0, "1": 1, "0": 0}
            ).astype(float)

    available = [c for c in FEATURE_COLS if c in df.columns]
    X = df[available].apply(pd.to_numeric, errors="coerce").fillna(0)
    y = df["label"].values

    n_train = int(len(df) * 0.8)
    n_val   = int(n_train * 0.15)
    X_inner, X_val, X_test = X.iloc[:n_train - n_val], X.iloc[n_train - n_val:n_train], X.iloc[n_train:]
    y_inner, y_val, y_test = y[:n_train - n_val], y[n_train - n_val:n_train], y[n_train:]

    imputer   = SimpleImputer(strategy="median")
    X_tr_imp  = imputer.fit_transform(X_inner)
    X_val_imp = imputer.transform(X_val)
    X_te_imp  = imputer.transform(X_test)

    n_neg = (y_inner == 0).sum()
    n_pos = (y_inner == 1).sum()
    spw   = n_neg / n_pos if n_pos > 0 else 1.0

    model = LGBMClassifier(
        n_estimators=500, num_leaves=31, learning_rate=0.05,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
        min_child_samples=20, scale_pos_weight=spw,
        random_state=42, verbose=-1, n_jobs=-1,
    )
    model.fit(
        X_tr_imp, y_inner,
        eval_set=[(X_val_imp, y_val)],
        callbacks=[early_stopping(30, verbose=False), log_evaluation(-1)],
    )

    probs_test  = model.predict_proba(X_te_imp)[:, 1]
    probs_train = model.predict_proba(X_tr_imp)[:, 1]
    auc_test  = roc_auc_score(y_test,  probs_test)  if len(set(y_test))  > 1 else 0.5
    auc_train = roc_auc_score(y_inner, probs_train) if len(set(y_inner)) > 1 else 0.5

    fi = dict(zip(available, model.feature_importances_))

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_DIR / "lgb_model.pkl", "wb") as f:
        pickle.dump(model, f)

    with open(MODEL_DIR / "imputer.pkl", "wb") as f:
        pickle.dump(imputer, f)

    meta = {
        "model_type":        "LightGBM",
        "feature_cols":      available,
        "signal_threshold":  0.65,
        "n_train":           int(len(X_inner)),
        "n_test":            int(len(X_test)),
        "auc_train":         round(float(auc_train), 4),
        "auc_test":          round(float(auc_test), 4),
        "precision_at_threshold": 0.0,
        "recall_at_threshold":    0.0,
        "f1_at_threshold":        0.0,
        "n_signals_test":    0,
        "scale_pos_weight":  round(float(spw), 4),
        "best_iteration":    model.best_iteration_,
        "trained_at":        datetime.now(tz=timezone.utc).isoformat(),
        "feature_importance": {k: int(v) for k, v in sorted(fi.items(), key=lambda x: -x[1])},
    }

    with open(MODEL_DIR / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"  [MODEL] Done — AUC train={auc_train:.3f} test={auc_test:.3f} | {len(df)} rows")


# ══════════════════════════════════════════════════════════════════════════════
# 4. Writer + Main
# ══════════════════════════════════════════════════════════════════════════════

def write_csv(path: Path, rows: list[dict], dry_run: bool):
    if not rows:
        print(f"  [SKIP] {path.name} — 0 rows")
        return
    first_ts = list(rows[0].values())[0]
    if dry_run:
        print(f"  [DRY]  {path.name:<25} {len(rows):>6} rows | first: {str(first_ts)[:19]}")
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  [OK]   {path.name:<25} {len(rows):>6} rows")


def main():
    args        = parse_args()
    out_dir     = Path(args.dir) if args.dir else DATA_DIR
    proc_dir    = Path(args.dir) if args.dir else PROCESSED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    proc_dir.mkdir(parents=True, exist_ok=True)

    hours     = args.hours if args.hours is not None else HOURS
    now       = datetime.now(tz=timezone.utc).replace(microsecond=0)
    n_minutes = int(hours * 60)
    t0        = now - timedelta(minutes=n_minutes - 1)

    print(f"\n{'━'*58}")
    print(f"  BTC Dashboard — Fake Data Generator")
    print(f"{'━'*58}")
    print(f"  Period    : {t0.strftime('%H:%M')} → {now.strftime('%H:%M')} UTC ({hours}h)")
    print(f"  Base price: ${BASE_PRICE:,.0f}  |  Liq Upper: ${LIQ_UPPER:,.0f}  Lower: ${LIQ_LOWER:,.0f}")
    print(f"  Output    : {out_dir}")
    print()

    # 1. Sinh 1m candles
    print("▶ Generating price data...")
    candles_1m = simulate_1m_candles(n_minutes, BASE_PRICE)
    final_price = candles_1m[-1]["close"]
    price_range = max(c["high"] for c in candles_1m) - min(c["low"] for c in candles_1m)
    print(f"  1m candles: {len(candles_1m)} | open=${candles_1m[0]['open']:,.0f}"
          f" → close=${final_price:,.0f} | range=${price_range:,.0f}")

    # 2. Ghi tất cả file
    print("\n▶ Writing CSV files...")
    if not args.features_only:
        klines_1s = gen_klines_1s(candles_1m, t0)
        write_csv(out_dir / "klines_1s.csv",     klines_1s,                              args.dry_run)
        write_csv(out_dir / "liquidations.csv",  gen_liquidations(candles_1m, t0),       args.dry_run)
        # orderbook: chỉ sinh 1 snapshot/phút để tránh file 300MB
        ob_rows = [gen_orderbook([c], t0 + timedelta(minutes=i))[0]
                   for i, c in enumerate(candles_1m)]
        write_csv(out_dir / "orderbook.csv",     ob_rows,                                args.dry_run)
        write_csv(out_dir / "aggtrades.csv",     gen_aggtrades(candles_1m, t0),          args.dry_run)
        write_csv(out_dir / "funding_rate.csv",  gen_funding(n_minutes, t0),             args.dry_run)
        write_csv(out_dir / "open_interest.csv", gen_open_interest(candles_1m, t0),      args.dry_run)

    features = gen_features(candles_1m, t0)
    write_csv(proc_dir / "features_5m.csv",  features,                               args.dry_run)
    if not args.features_only:
        write_csv(proc_dir / "paper_trades.csv", gen_trades(candles_1m, t0, now),        args.dry_run)

    label_counts = {0: sum(1 for r in features if r["label"] == 0),
                    1: sum(1 for r in features if r["label"] == 1)}
    print(f"\n  features_5m labels: label=0 → {label_counts[0]}, label=1 → {label_counts[1]}")

    # 3. Train model
    if not args.no_model and not args.dry_run:
        print("\n▶ Training mock model...")
        features_file = proc_dir / "features_5m.csv"
        train_mock_model(features_file, args.dry_run)

    print(f"\n{'━'*58}")
    print(f"  {'Done (dry-run)' if args.dry_run else 'Done ✓  Restart server để thấy data mới'}")
    print(f"{'━'*58}\n")


if __name__ == "__main__":
    main()
