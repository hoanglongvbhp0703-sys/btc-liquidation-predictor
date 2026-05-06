"""
feat_price.py — Features từ klines_1s.csv

Input : DataFrame từ load_klines(), đã lọc cửa sổ thời gian cần tính
Output: dict các features giá
"""

import numpy as np
import pandas as pd


def compute_price_features(df_klines: pd.DataFrame) -> dict:
    """
    df_klines: tất cả các dòng trong cửa sổ 5 phút (≈300 dòng)
               cột cần: open_time, close, high, low, volume, taker_buy_vol

    Returns dict:
      current_price     — giá close mới nhất
      price_change_5m   — % thay đổi so với đầu cửa sổ
      price_change_1m   — % thay đổi 1 phút gần nhất
      volatility_5m     — độ lệch chuẩn của close
      volume_5m         — tổng volume 5 phút
      taker_buy_ratio   — tỉ lệ buy volume / total volume
                          > 0.5 → áp lực mua mạnh hơn bán
    """
    if df_klines.empty:
        return _empty_price_features()

    df = df_klines.sort_values("open_time")
    close = df["close"].values

    current_price   = float(close[-1])
    open_price_5m   = float(close[0])
    open_price_1m   = float(close[max(0, len(close) - 60)])

    price_change_5m = (current_price - open_price_5m) / open_price_5m if open_price_5m else 0.0
    price_change_1m = (current_price - open_price_1m) / open_price_1m if open_price_1m else 0.0
    volatility_5m   = float(np.std(close)) if len(close) > 1 else 0.0

    total_volume    = float(df["volume"].sum())
    taker_buy_vol   = float(df["taker_buy_vol"].sum())
    taker_buy_ratio = taker_buy_vol / total_volume if total_volume > 0 else 0.5

    return {
        "current_price":   current_price,
        "price_change_5m": round(price_change_5m, 6),
        "price_change_1m": round(price_change_1m, 6),
        "volatility_5m":   round(volatility_5m, 4),
        "volume_5m":       round(total_volume, 4),
        "taker_buy_ratio": round(taker_buy_ratio, 6),
    }


def _empty_price_features() -> dict:
    return {
        "current_price":   None,
        "price_change_5m": None,
        "price_change_1m": None,
        "volatility_5m":   None,
        "volume_5m":       None,
        "taker_buy_ratio": None,
    }