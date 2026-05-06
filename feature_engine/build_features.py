"""
build_features.py — Merge tất cả features thành 1 row tại thời điểm T

Đây là hàm trung tâm của Tầng 2.
Gọi từ run.py mỗi 5 phút.
"""

import pandas as pd
from datetime import timedelta

from load_data import (
    load_klines, load_liquidations, load_orderbook,
    load_aggtrades, load_open_interest, load_funding_rate,
)
from feat_price       import compute_price_features
from feat_liquidation import compute_liquidation_features
from feat_orderbook   import compute_orderbook_features
from feat_aggtrade    import compute_aggtrade_features
from feat_oi          import compute_oi_features        # ✅ fix: tách riêng
from feat_funding     import compute_funding_features   # ✅ fix: tách riêng


def build_feature_row(at_time: pd.Timestamp) -> dict:
    """
    Tính tất cả features tại thời điểm `at_time`.
    Dùng dữ liệu từ [at_time - 4h, at_time].

    Returns: dict 1 row — sẵn sàng append vào features_5m.csv
    """
    now    = at_time
    ago_5m = now - timedelta(minutes=5)
    ago_4h = now - timedelta(hours=4)

    # ── Load data ───────────────────────────────────────────
    df_klines   = load_klines(since=ago_5m)
    df_liq_5m   = load_liquidations(since=ago_5m)
    df_liq_4h   = load_liquidations(since=ago_4h)
    df_ob       = load_orderbook(since=ago_5m)
    df_agg      = load_aggtrades(since=ago_5m)
    df_oi       = load_open_interest(since=ago_4h)
    df_funding  = load_funding_rate(since=ago_4h)

    # ── Tính features ───────────────────────────────────────
    price_feats   = compute_price_features(df_klines)
    current_price = price_feats.get("current_price")

    liq_feats     = compute_liquidation_features(df_liq_5m, df_liq_4h, current_price)
    ob_feats      = compute_orderbook_features(df_ob)
    agg_feats     = compute_aggtrade_features(df_agg)
    oi_feats      = compute_oi_features(df_oi)
    funding_feats = compute_funding_features(df_funding)

    # ── Merge thành 1 row ───────────────────────────────────
    row = {"timestamp": now.isoformat(), "label": ""}
    row.update(price_feats)
    row.update(liq_feats)
    row.update(ob_feats)
    row.update(agg_feats)
    row.update(oi_feats)
    row.update(funding_feats)

    return row


# Thứ tự columns cố định cho CSV
FEATURE_COLUMNS = [
    "timestamp",

    # Giá
    "current_price",
    "price_change_5m", "price_change_1m",
    "volatility_5m", "volume_5m", "taker_buy_ratio",

    # Liquidation
    "liq_long_usd_5m", "liq_short_usd_5m", "liq_total_5m", "liq_ratio_5m",
    "liq_zone_upper", "liq_zone_lower",
    "dist_to_upper", "dist_to_lower",

    # Order Book
    "imbalance_now", "imbalance_avg_1m", "imbalance_trend",
    "spread_now", "bid_vol_now", "ask_vol_now", "wall_ratio", "mid_price_now",

    # CVD + Whale
    "cvd_delta_5m", "cvd_delta_1m",
    "whale_buy_count", "whale_sell_count", "whale_net",
    "whale_buy_usd_5m", "whale_sell_usd_5m", "whale_dominance",

    # Open Interest
    "oi_now", "oi_usd_now",
    "delta_oi_5m", "delta_oi_30m", "delta_oi_1h", "oi_acceleration",

    # Funding — ✅ fix: đồng bộ đủ 9 fields từ feat_funding.py
    "funding_rate",
    "funding_rate_abs",
    "funding_bias",
    "funding_long_heavy",
    "funding_short_heavy",
    "funding_rate_change",
    "funding_trend_3h",
    "secs_to_next_funding",
    "funding_urgency",

    # Label (điền sau 30 phút bởi label_builder.py)
    "label",
]