"""
feat_orderbook.py — Features từ orderbook.csv

Input : DataFrame từ load_orderbook()
Output: dict các features order book

Cấu trúc CSV thực tế (1 dòng):
  timestamp, bid1_price, bid1_qty, ..., bid5_price, bid5_qty,
  ask1_price, ask1_qty, ..., ask5_price, ask5_qty,
  mid_price, spread, bid_vol_total, ask_vol_total, imbalance
"""

import numpy as np
import pandas as pd


def compute_orderbook_features(df_ob: pd.DataFrame) -> dict:
    """
    df_ob: cửa sổ 60-300 dòng gần nhất (1-5 phút)
           các features đã tính sẵn trong CSV: imbalance, spread, mid_price,
           bid_vol_total, ask_vol_total

    Returns dict:
      imbalance_now      — imbalance snapshot mới nhất
                           > 0.55 → áp lực mua, < 0.45 → áp lực bán
      imbalance_avg_1m   — trung bình imbalance 60s gần nhất
      imbalance_trend    — imbalance_now - imbalance_avg_1m
                           > 0 → áp lực mua đang tăng
      spread_now         — spread (ask1 - bid1) mới nhất
                           spread nới rộng → thanh khoản giảm → sắp biến động
      bid_vol_now        — tổng qty 5 bid levels mới nhất
      ask_vol_now        — tổng qty 5 ask levels mới nhất
      wall_ratio         — max_bid_qty / (max_bid_qty + max_ask_qty)
                           > 0.6 → có bid wall lớn → hỗ trợ giá
      mid_price_now      — mid price mới nhất
    """
    if df_ob.empty:
        return _empty_ob_features()

    df = df_ob.sort_values("timestamp")
    latest = df.iloc[-1]
    last_60 = df.tail(60)  # ~60 giây gần nhất

    imbalance_now    = float(latest["imbalance"])
    imbalance_avg_1m = float(last_60["imbalance"].mean())
    imbalance_trend  = imbalance_now - imbalance_avg_1m

    spread_now   = float(latest["spread"])
    bid_vol_now  = float(latest["bid_vol_total"])
    ask_vol_now  = float(latest["ask_vol_total"])
    mid_price    = float(latest["mid_price"])

    # Wall: level nào có qty lớn nhất trong top 5
    bid_qty_cols = ["bid1_qty", "bid2_qty", "bid3_qty", "bid4_qty", "bid5_qty"]
    ask_qty_cols = ["ask1_qty", "ask2_qty", "ask3_qty", "ask4_qty", "ask5_qty"]

    max_bid_qty = float(latest[bid_qty_cols].max())
    max_ask_qty = float(latest[ask_qty_cols].max())
    wall_denom  = max_bid_qty + max_ask_qty
    wall_ratio  = max_bid_qty / wall_denom if wall_denom > 0 else 0.5

    return {
        "imbalance_now":    round(imbalance_now, 6),
        "imbalance_avg_1m": round(imbalance_avg_1m, 6),
        "imbalance_trend":  round(imbalance_trend, 6),
        "spread_now":       round(spread_now, 4),
        "bid_vol_now":      round(bid_vol_now, 4),
        "ask_vol_now":      round(ask_vol_now, 4),
        "wall_ratio":       round(wall_ratio, 6),
        "mid_price_now":    round(mid_price, 2),
    }


def _empty_ob_features() -> dict:
    return {
        "imbalance_now":    None,
        "imbalance_avg_1m": None,
        "imbalance_trend":  None,
        "spread_now":       None,
        "bid_vol_now":      None,
        "ask_vol_now":      None,
        "wall_ratio":       None,
        "mid_price_now":    None,
    }