"""
feat_liquidation.py — Features từ liquidations.csv

Input : DataFrame từ load_liquidations()
Output: dict các features liquidation

Lưu ý về side:
  BUY  = lệnh SHORT bị liquidate → sàn buộc MUA vào → giá bị đẩy LÊN
  SELL = lệnh LONG  bị liquidate → sàn buộc BÁN ra → giá bị đẩy XUỐNG

Lưu ý quan trọng:
  liquidations.csv chứa TẤT CẢ symbols (PEPEUSDT, ETHUSDT, SKYAIUSDT...)
  → Volume 5m: dùng tất cả (thị trường rộng)
  → Zone calculation: CHỈ dùng BTCUSDT (giá altcoin sẽ làm lệch percentile)
"""

import numpy as np
import pandas as pd

BTCUSDT = "BTCUSDT"
MIN_PRICES_FOR_ZONE = 5    # ít nhất 5 điểm; BTC ~5 liq/h → zone có sau ~1h


def compute_liquidation_features(
    df_liq_5m: pd.DataFrame,   # liquidation trong 5 phút gần nhất
    df_liq_4h: pd.DataFrame,   # liquidation trong 4 giờ gần nhất (để tính vùng)
    current_price: float,
) -> dict:
    """
    df_liq_5m : cửa sổ 5 phút  — tính volume bị quét (tất cả symbols)
    df_liq_4h : cửa sổ 4 giờ   — tính vùng thanh khoản (chỉ BTCUSDT)
    current_price: giá hiện tại để tính khoảng cách

    Returns dict:
      liq_long_usd_5m    — tổng USD LONG bị quét trong 5 phút (tất cả symbols)
      liq_short_usd_5m   — tổng USD SHORT bị quét trong 5 phút (tất cả symbols)
      liq_total_5m       — tổng cộng
      liq_ratio_5m       — short_usd / total  (> 0.7 → SHORT đang bị quét nhiều)
      liq_zone_upper     — percentile 90 giá SHORT bị quét trong 4h (chỉ BTCUSDT)
      liq_zone_lower     — percentile 10 giá LONG bị quét trong 4h (chỉ BTCUSDT)
      dist_to_upper      — % khoảng cách từ giá hiện tại đến vùng trên
      dist_to_lower      — % khoảng cách từ giá hiện tại đến vùng dưới
    """
    # ── 5 phút — tất cả symbols ───────────────────────────
    if df_liq_5m.empty:
        liq_long_usd_5m  = 0.0
        liq_short_usd_5m = 0.0
    else:
        liq_long_usd_5m  = float(df_liq_5m[df_liq_5m["side"] == "SELL"]["usd_value"].sum())
        liq_short_usd_5m = float(df_liq_5m[df_liq_5m["side"] == "BUY"]["usd_value"].sum())

    liq_total_5m = liq_long_usd_5m + liq_short_usd_5m
    liq_ratio_5m = liq_short_usd_5m / (liq_total_5m + 1e-9)

    # ── 4 giờ — CHỈ BTCUSDT cho zone calculation ─────────
    liq_zone_upper = None
    liq_zone_lower = None
    dist_to_upper  = None
    dist_to_lower  = None

    if not df_liq_4h.empty:
        # ✅ Fix: chỉ lấy BTCUSDT để tính zone
        df_btc = df_liq_4h[df_liq_4h["symbol"] == BTCUSDT]

        # SHORT bị quét tại vùng GIÁ CAO → vùng thanh khoản phía trên
        short_prices = df_btc[df_btc["side"] == "BUY"]["price"]
        if len(short_prices) >= MIN_PRICES_FOR_ZONE:
            liq_zone_upper = float(np.percentile(short_prices, 90))

        # LONG bị quét tại vùng GIÁ THẤP → vùng thanh khoản phía dưới
        long_prices = df_btc[df_btc["side"] == "SELL"]["price"]
        if len(long_prices) >= MIN_PRICES_FOR_ZONE:
            liq_zone_lower = float(np.percentile(long_prices, 10))

        if liq_zone_upper and current_price:
            dist_to_upper = (liq_zone_upper - current_price) / current_price

        if liq_zone_lower and current_price:
            dist_to_lower = (current_price - liq_zone_lower) / current_price

    return {
        "liq_long_usd_5m":  round(liq_long_usd_5m, 2),
        "liq_short_usd_5m": round(liq_short_usd_5m, 2),
        "liq_total_5m":     round(liq_total_5m, 2),
        "liq_ratio_5m":     round(liq_ratio_5m, 6),
        "liq_zone_upper":   round(liq_zone_upper, 2) if liq_zone_upper else None,
        "liq_zone_lower":   round(liq_zone_lower, 2) if liq_zone_lower else None,
        "dist_to_upper":    round(dist_to_upper, 6)  if dist_to_upper is not None else None,
        "dist_to_lower":    round(dist_to_lower, 6)  if dist_to_lower is not None else None,
    }