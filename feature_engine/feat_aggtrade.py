"""feat_aggtrade.py — Features CVD + Whale từ aggtrades.csv (cửa sổ 1 phút)."""

import pandas as pd

WHALE_THRESHOLD_USD = 50_000


def compute_aggtrade_features(df_agg: pd.DataFrame) -> dict:
    if df_agg.empty:
        return _empty_agg_features()

    df = df_agg.sort_values("timestamp")

    cvd_delta_1m = float(df["cvd_delta"].sum())

    t_30s_ago    = df["timestamp"].max() - pd.Timedelta(seconds=30)
    df_30s       = df[df["timestamp"] >= t_30s_ago]
    cvd_delta_30s = float(df_30s["cvd_delta"].sum()) if not df_30s.empty else 0.0

    df_whale = df[
        (df["agg_id"].astype(str) != "BATCH") &
        (df["usd_value"] >= WHALE_THRESHOLD_USD)
    ]

    if df_whale.empty:
        whale_buy_count   = 0
        whale_sell_count  = 0
        whale_buy_usd_1m  = 0.0
        whale_sell_usd_1m = 0.0
    else:
        df_whale_buy  = df_whale[df_whale["is_buyer_maker"] == False]
        df_whale_sell = df_whale[df_whale["is_buyer_maker"] == True]

        whale_buy_count   = len(df_whale_buy)
        whale_sell_count  = len(df_whale_sell)
        whale_buy_usd_1m  = float(df_whale_buy["usd_value"].sum())
        whale_sell_usd_1m = float(df_whale_sell["usd_value"].sum())

    whale_net   = whale_buy_count - whale_sell_count
    whale_total = whale_buy_usd_1m + whale_sell_usd_1m
    whale_dominance = whale_buy_usd_1m / whale_total if whale_total > 0 else 0.5

    return {
        "cvd_delta_1m":      round(cvd_delta_1m, 4),
        "cvd_delta_30s":     round(cvd_delta_30s, 4),
        "whale_buy_count":   whale_buy_count,
        "whale_sell_count":  whale_sell_count,
        "whale_net":         whale_net,
        "whale_buy_usd_1m":  round(whale_buy_usd_1m, 2),
        "whale_sell_usd_1m": round(whale_sell_usd_1m, 2),
        "whale_dominance":   round(whale_dominance, 6),
    }


def _empty_agg_features() -> dict:
    return {
        "cvd_delta_1m":      None,
        "cvd_delta_30s":     None,
        "whale_buy_count":   None,
        "whale_sell_count":  None,
        "whale_net":         None,
        "whale_buy_usd_1m":  None,
        "whale_sell_usd_1m": None,
        "whale_dominance":   None,
    }
