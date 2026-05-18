"""feat_price.py — Features từ klines_1s.csv (cửa sổ 1 phút)."""

import numpy as np
import pandas as pd


def compute_price_features(df_klines: pd.DataFrame) -> dict:
    """
    df_klines: ~60 rows (1s snapshots trong 1 phút gần nhất)
    """
    if df_klines.empty:
        return _empty_price_features()

    df = df_klines.sort_values("open_time")
    close = df["close"].values

    current_price   = float(close[-1])
    open_price_1m   = float(close[0])
    open_price_30s  = float(close[max(0, len(close) - 30)])

    price_change_1m  = (current_price - open_price_1m)  / open_price_1m  if open_price_1m  else 0.0
    price_change_30s = (current_price - open_price_30s) / open_price_30s if open_price_30s else 0.0
    volatility_1m    = float(np.std(close)) if len(close) > 1 else 0.0

    # volume/taker_buy_vol là cumulative kể từ đầu nến → dùng snapshot cuối, không sum
    total_volume    = float(df["volume"].iloc[-1])
    taker_buy_vol   = float(df["taker_buy_vol"].iloc[-1])
    taker_buy_ratio = taker_buy_vol / total_volume if total_volume > 0 else 0.5

    return {
        "current_price":    current_price,
        "price_change_1m":  round(price_change_1m,  6),
        "price_change_30s": round(price_change_30s, 6),
        "volatility_1m":    round(volatility_1m, 4),
        "volume_1m":        round(total_volume, 4),
        "taker_buy_ratio":  round(taker_buy_ratio, 6),
    }


def _empty_price_features() -> dict:
    return {
        "current_price":    None,
        "price_change_1m":  None,
        "price_change_30s": None,
        "volatility_1m":    None,
        "volume_1m":        None,
        "taker_buy_ratio":  None,
    }
