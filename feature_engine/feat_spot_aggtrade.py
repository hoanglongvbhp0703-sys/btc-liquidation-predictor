"""feat_spot_aggtrade.py — Spot CVD features từ spot_aggtrades.csv (cửa sổ 1 phút)."""

import pandas as pd


def compute_spot_aggtrade_features(df_spot: pd.DataFrame) -> dict:
    if df_spot.empty:
        return _empty()

    df = df_spot.sort_values("timestamp")

    spot_cvd_delta_1m = float(df["cvd_delta"].sum())

    t_30s_ago         = df["timestamp"].max() - pd.Timedelta(seconds=30)
    df_30s            = df[df["timestamp"] >= t_30s_ago]
    spot_cvd_delta_30s = float(df_30s["cvd_delta"].sum()) if not df_30s.empty else 0.0

    return {
        "spot_cvd_delta_1m":  round(spot_cvd_delta_1m,  4),
        "spot_cvd_delta_30s": round(spot_cvd_delta_30s, 4),
    }


def _empty() -> dict:
    return {
        "spot_cvd_delta_1m":  None,
        "spot_cvd_delta_30s": None,
    }
