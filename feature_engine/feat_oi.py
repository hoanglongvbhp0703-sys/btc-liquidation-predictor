"""
feat_oi.py — Features từ open_interest.csv

Input : DataFrame từ load_open_interest()
Output: dict các features Open Interest

Cấu trúc CSV thực tế (1 dòng):
  timestamp, oi_btc, oi_usd
  2026-05-04T03:51:36+00:00,108012.996,8664446096.23320

Context:
  - OI được poll mỗi 30 giây
  - OI tăng → tiền mới vào thị trường → sắp có biến động lớn
  - OI giảm → lệnh đang đóng bớt → thị trường hạ nhiệt
  - OI tăng + giá tăng → xu hướng tăng có tiền hỗ trợ (bullish)
  - OI tăng + giá giảm → xu hướng giảm có tiền hỗ trợ (bearish)
  - OI giảm + giá tăng → short covering, không bền (cảnh báo)
  - OI giảm + giá giảm → long liquidation, có thể tiếp tục giảm
"""

import pandas as pd


def compute_oi_features(df_oi: pd.DataFrame) -> dict:
    """
    df_oi: tất cả dữ liệu OI trong cửa sổ đã load (thường 4h)
           cột: timestamp, oi_btc, oi_usd

    Returns dict:
      oi_now          — OI BTC mới nhất (số hợp đồng quy đổi BTC)
      oi_usd_now      — OI USD mới nhất
      delta_oi_5m     — % thay đổi OI trong 5 phút
                        > 0 → tiền mới vào → sắp có biến động
                        < 0 → lệnh đang đóng bớt → hạ nhiệt
      delta_oi_30m    — % thay đổi OI trong 30 phút
                        tăng đột biến → biến động lớn sắp xảy ra
      delta_oi_1h     — % thay đổi OI trong 1 giờ
                        context dài hơn cho model
      oi_acceleration — delta_oi_5m - delta_oi_30m/6
                        > 0 → OI đang tăng tốc (tiền vào nhanh hơn)
                        < 0 → OI đang giảm tốc
    """
    if df_oi.empty or len(df_oi) < 2:
        return _empty_oi_features()

    df     = df_oi.sort_values("timestamp").reset_index(drop=True)
    latest = df.iloc[-1]
    t_now  = df["timestamp"].max()

    oi_now     = float(latest["oi_btc"])
    oi_usd_now = float(latest["oi_usd"])

    delta_oi_1m  = _calc_delta(df, t_now, minutes=1,  col="oi_btc")
    delta_oi_30m = _calc_delta(df, t_now, minutes=30, col="oi_btc")
    delta_oi_1h  = _calc_delta(df, t_now, minutes=60, col="oi_btc")

    oi_acceleration = None
    if delta_oi_1m is not None and delta_oi_30m is not None:
        oi_acceleration = round(delta_oi_1m - (delta_oi_30m / 30), 8)

    return {
        "oi_now":          round(oi_now, 3),
        "oi_usd_now":      round(oi_usd_now, 2),
        "delta_oi_1m":     round(delta_oi_1m,  8) if delta_oi_1m  is not None else None,
        "delta_oi_30m":    round(delta_oi_30m, 8) if delta_oi_30m is not None else None,
        "delta_oi_1h":     round(delta_oi_1h,  8) if delta_oi_1h  is not None else None,
        "oi_acceleration": oi_acceleration,
    }


def _calc_delta(
    df: pd.DataFrame,
    t_now: pd.Timestamp,
    minutes: int,
    col: str,
) -> float | None:
    """Tính % thay đổi của `col` từ `minutes` phút trước đến now."""
    t_ago = t_now - pd.Timedelta(minutes=minutes)
    df_past = df[df["timestamp"] <= t_ago]
    if df_past.empty:
        return None
    val_past = float(df_past.iloc[-1][col])
    val_now  = float(df.iloc[-1][col])
    if val_past == 0:
        return None
    return (val_now - val_past) / val_past


def _empty_oi_features() -> dict:
    return {
        "oi_now":          None,
        "oi_usd_now":      None,
        "delta_oi_1m":     None,
        "delta_oi_30m":    None,
        "delta_oi_1h":     None,
        "oi_acceleration": None,
    }