"""build_features.py — Merge tất cả features thành 1 row tại thời điểm T (1m granularity)."""

import pandas as pd
from datetime import timedelta

from load_data import (
    load_klines, load_liquidations, load_orderbook,
    load_aggtrades, load_open_interest, load_premium_index,
    load_spot_aggtrades,
)
from feat_price          import compute_price_features
from feat_liquidation    import compute_liquidation_features
from feat_orderbook      import compute_orderbook_features
from feat_aggtrade       import compute_aggtrade_features
from feat_spot_aggtrade  import compute_spot_aggtrade_features
from feat_oi             import compute_oi_features
from feat_funding        import compute_funding_features
from feat_basis          import compute_basis_features


def build_feature_row(at_time: pd.Timestamp) -> dict:
    now    = at_time
    ago_1m = now - timedelta(minutes=1)
    ago_4h = now - timedelta(hours=4)

    df_klines      = load_klines(since=ago_1m)
    df_liq_1m      = load_liquidations(since=ago_1m)
    df_ob          = load_orderbook(since=ago_1m)
    df_agg         = load_aggtrades(since=ago_1m)
    df_spot        = load_spot_aggtrades(since=ago_1m)
    df_oi          = load_open_interest(since=ago_4h)
    df_premium     = load_premium_index(since=ago_4h)   # funding + basis từ 1 CSV

    price_feats      = compute_price_features(df_klines)
    liq_feats        = compute_liquidation_features(df_liq_1m)
    ob_feats         = compute_orderbook_features(df_ob)
    agg_feats        = compute_aggtrade_features(df_agg)
    spot_feats       = compute_spot_aggtrade_features(df_spot)
    oi_feats         = compute_oi_features(df_oi)
    funding_feats    = compute_funding_features(df_premium)
    basis_feats      = compute_basis_features(df_premium)

    row = {"timestamp": now.isoformat()}
    row.update(price_feats)
    row.update(liq_feats)
    row.update(ob_feats)
    row.update(agg_feats)
    row.update(spot_feats)
    row.update(oi_feats)
    row.update(funding_feats)
    row.update(basis_feats)

    # Divergence: futures CVD - spot CVD
    # Dương → futures đang bán nhiều hơn spot → bearish pressure từ derivatives
    # Âm → spot đang mua mạnh hơn futures → potential short squeeze signal
    fut_cvd  = agg_feats.get("cvd_delta_1m")
    spot_cvd = spot_feats.get("spot_cvd_delta_1m")
    if fut_cvd is not None and spot_cvd is not None:
        row["cvd_divergence"] = round(float(fut_cvd) - float(spot_cvd), 4)
    else:
        row["cvd_divergence"] = None

    return row


FEATURE_COLUMNS = [
    "timestamp",

    # Giá
    "current_price",
    "price_change_1m", "price_change_30s",
    "volatility_1m", "volume_1m", "taker_buy_ratio",

    # Liquidation
    "liq_long_usd_1m", "liq_short_usd_1m", "liq_total_1m", "liq_ratio_1m",
    "liq_accel_30s",

    # Order Book
    "imbalance_now", "imbalance_avg_1m", "imbalance_trend",
    "spread_now", "bid_vol_now", "ask_vol_now", "wall_ratio", "mid_price_now",

    # CVD + Whale
    "cvd_delta_1m", "cvd_delta_30s",
    "whale_buy_count", "whale_sell_count", "whale_net",
    "whale_buy_usd_1m", "whale_sell_usd_1m", "whale_dominance",

    # Open Interest
    "oi_now", "oi_usd_now",
    "delta_oi_1m", "delta_oi_30m", "delta_oi_1h", "oi_acceleration",

    # Funding
    "funding_rate", "funding_rate_abs", "funding_bias",
    "funding_long_heavy", "funding_short_heavy",
    "funding_rate_change", "funding_trend_3h",
    "secs_to_next_funding", "funding_urgency",

    # Spot CVD (divergence với futures)
    "spot_cvd_delta_1m", "spot_cvd_delta_30s",

    # Futures-spot basis
    "basis_pct", "basis_change_1m", "basis_positive",

    # Tổng hợp
    "cvd_divergence",
]
