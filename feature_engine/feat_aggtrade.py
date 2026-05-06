"""
feat_aggtrade.py — Features CVD + Whale từ aggtrades.csv

Input : DataFrame từ load_aggtrades()
Output: dict các features CVD và whale activity

Cấu trúc CSV thực tế (1 dòng):
  timestamp, agg_id, price, qty, usd_value, is_buyer_maker, cvd_delta

agg_id = "BATCH"   → dòng tổng hợp 1s (lệnh nhỏ)
agg_id = số nguyên → lệnh lớn riêng lẻ (≥ $50K)

is_buyer_maker = False → mua chủ động (buyer là taker) → cvd_delta > 0
is_buyer_maker = True  → bán chủ động (seller là taker) → cvd_delta < 0
"""

import numpy as np
import pandas as pd

WHALE_THRESHOLD_USD = 50_000  # $50K


def compute_aggtrade_features(df_agg: pd.DataFrame) -> dict:
    """
    df_agg: cửa sổ 5 phút gần nhất từ aggtrades.csv

    Returns dict:
      cvd_delta_5m       — tổng CVD delta trong 5 phút
                           > 0 → phe mua kiểm soát
                           < 0 → phe bán kiểm soát
      cvd_delta_1m       — tổng CVD delta trong 1 phút gần nhất
      whale_buy_count    — số lệnh whale mua CĐ (≥$50K)
      whale_sell_count   — số lệnh whale bán CĐ (≥$50K)
      whale_net          — whale_buy - whale_sell
                           > 0 → cá mập đang tích lũy
      whale_buy_usd_5m   — tổng USD whale mua CĐ
      whale_sell_usd_5m  — tổng USD whale bán CĐ
      whale_dominance    — whale_buy_usd / (whale_buy_usd + whale_sell_usd)
    """
    if df_agg.empty:
        return _empty_agg_features()

    df = df_agg.sort_values("timestamp")

    # ── CVD tổng 5 phút ────────────────────────────────────
    # Dùng cột cvd_delta đã tính sẵn trong CSV
    cvd_delta_5m = float(df["cvd_delta"].sum())

    # CVD 1 phút gần nhất
    t_1m_ago     = df["timestamp"].max() - pd.Timedelta(minutes=1)
    df_1m        = df[df["timestamp"] >= t_1m_ago]
    cvd_delta_1m = float(df_1m["cvd_delta"].sum()) if not df_1m.empty else 0.0

    # ── Whale (lệnh riêng lẻ ≥ $50K, agg_id != "BATCH") ───
    df_whale = df[
        (df["agg_id"].astype(str) != "BATCH") &
        (df["usd_value"] >= WHALE_THRESHOLD_USD)
    ]

    if df_whale.empty:
        whale_buy_count   = 0
        whale_sell_count  = 0
        whale_buy_usd_5m  = 0.0
        whale_sell_usd_5m = 0.0
    else:
        # is_buyer_maker = False → mua chủ động
        df_whale_buy  = df_whale[df_whale["is_buyer_maker"] == False]
        df_whale_sell = df_whale[df_whale["is_buyer_maker"] == True]

        whale_buy_count   = len(df_whale_buy)
        whale_sell_count  = len(df_whale_sell)
        whale_buy_usd_5m  = float(df_whale_buy["usd_value"].sum())
        whale_sell_usd_5m = float(df_whale_sell["usd_value"].sum())

    whale_net   = whale_buy_count - whale_sell_count
    whale_total = whale_buy_usd_5m + whale_sell_usd_5m
    whale_dominance = whale_buy_usd_5m / whale_total if whale_total > 0 else 0.5

    return {
        "cvd_delta_5m":      round(cvd_delta_5m, 4),
        "cvd_delta_1m":      round(cvd_delta_1m, 4),
        "whale_buy_count":   whale_buy_count,
        "whale_sell_count":  whale_sell_count,
        "whale_net":         whale_net,
        "whale_buy_usd_5m":  round(whale_buy_usd_5m, 2),
        "whale_sell_usd_5m": round(whale_sell_usd_5m, 2),
        "whale_dominance":   round(whale_dominance, 6),
    }


def _empty_agg_features() -> dict:
    return {
        "cvd_delta_5m":      None,
        "cvd_delta_1m":      None,
        "whale_buy_count":   None,
        "whale_sell_count":  None,
        "whale_net":         None,
        "whale_buy_usd_5m":  None,
        "whale_sell_usd_5m": None,
        "whale_dominance":   None,
    }