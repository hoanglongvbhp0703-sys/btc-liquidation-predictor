"""
feat_basis.py — Futures-spot basis features từ basis.csv

basis_pct > 0: futures premium → longs nhiều, shorts at risk → short squeeze tiềm năng
basis_pct < 0: futures discount → shorts nhiều, longs at risk → long liquidation tiềm năng

basis_change_1m: basis đang tăng (đang bullish) hay giảm (đang bearish)
"""

import pandas as pd


def compute_basis_features(df_basis: pd.DataFrame) -> dict:
    if df_basis.empty:
        return _empty()

    df = df_basis.sort_values("timestamp").reset_index(drop=True)
    latest     = df.iloc[-1]
    basis_pct  = float(latest["basis_pct"])

    # Thay đổi basis trong 1 phút qua
    t_1m_ago = df["timestamp"].max() - pd.Timedelta(minutes=1)
    df_1m    = df[df["timestamp"] >= t_1m_ago]
    basis_change_1m = None
    if len(df_1m) >= 2:
        oldest = float(df_1m.iloc[0]["basis_pct"])
        basis_change_1m = round(basis_pct - oldest, 6)

    return {
        "basis_pct":        round(basis_pct, 6),
        "basis_change_1m":  basis_change_1m,
        "basis_positive":   bool(basis_pct > 0),
    }


def _empty() -> dict:
    return {
        "basis_pct":       None,
        "basis_change_1m": None,
        "basis_positive":  None,
    }
