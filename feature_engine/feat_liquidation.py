"""feat_liquidation.py — Features từ liquidations.csv (cửa sổ 1 phút).

liq_short_usd = usd_value where side == 'BUY'  (SHORT bị liq → giá TĂNG)
liq_long_usd  = usd_value where side == 'SELL' (LONG bị liq  → giá GIẢM)
"""

import pandas as pd


def compute_liquidation_features(
    df_liq_1m: pd.DataFrame,   # liquidation trong 1 phút gần nhất
) -> dict:
    if df_liq_1m.empty:
        return _empty_liq_features()

    df = df_liq_1m.copy()
    df["liq_short"] = df["usd_value"].where(df["side"] == "BUY",  0.0)
    df["liq_long"]  = df["usd_value"].where(df["side"] == "SELL", 0.0)

    liq_long_usd_1m  = float(df["liq_long"].sum())
    liq_short_usd_1m = float(df["liq_short"].sum())
    liq_total_1m     = liq_long_usd_1m + liq_short_usd_1m
    liq_ratio_1m     = liq_short_usd_1m / (liq_total_1m + 1e-9)

    # Acceleration: so sánh 30s đầu vs 30s cuối trong window 1m
    t_max = df["event_time"].max()
    t_mid = t_max - pd.Timedelta(seconds=30)
    first_half  = df[df["event_time"] <  t_mid]["usd_value"].sum()
    second_half = df[df["event_time"] >= t_mid]["usd_value"].sum()
    liq_accel_30s = float(second_half - first_half)

    return {
        "liq_long_usd_1m":  round(liq_long_usd_1m, 2),
        "liq_short_usd_1m": round(liq_short_usd_1m, 2),
        "liq_total_1m":     round(liq_total_1m, 2),
        "liq_ratio_1m":     round(liq_ratio_1m, 6),
        "liq_accel_30s":    round(liq_accel_30s, 2),
    }


def _empty_liq_features() -> dict:
    return {
        "liq_long_usd_1m":  0.0,
        "liq_short_usd_1m": 0.0,
        "liq_total_1m":     0.0,
        "liq_ratio_1m":     0.5,
        "liq_accel_30s":    0.0,
    }
