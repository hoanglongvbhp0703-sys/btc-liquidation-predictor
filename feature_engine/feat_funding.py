"""
feat_funding.py — Features từ funding_rate.csv

Input : DataFrame từ load_funding_rate()
Output: dict các features funding rate

Cấu trúc CSV thực tế (1 dòng):
  timestamp, funding_rate, next_funding_time
  2026-05-04T03:50:39+00:00,0.00005127,2026-05-04T08:00:00+00:00

Context:
  - Funding rate cập nhật mỗi 1 giờ (polling REST)
  - Thanh toán thực tế diễn ra mỗi 8 giờ (00:00, 08:00, 16:00 UTC)
  - > +0.01%  → thị trường nghiêng LONG quá nhiều → dễ bị quét lên
  - < -0.01%  → thị trường nghiêng SHORT quá nhiều → dễ bị quét xuống
  - Gần thời điểm thanh toán: trader đóng lệnh để tránh phí → biến động tăng
"""

import numpy as np
import pandas as pd

# Ngưỡng đánh giá độ nghiêng thị trường
FUNDING_LONG_HEAVY  = +0.0001   # +0.01% → LONG quá nhiều
FUNDING_SHORT_HEAVY = -0.0001   # -0.01% → SHORT quá nhiều

# Thời điểm thanh toán trong ngày (giờ UTC): 00:00, 08:00, 16:00
FUNDING_PAYMENT_HOURS = [0, 8, 16]


def compute_funding_features(df_funding: pd.DataFrame) -> dict:
    """
    df_funding: tất cả dữ liệu funding rate (thường dùng cửa sổ 4h–24h)
                cột: timestamp, funding_rate, next_funding_time

    Returns dict:
      funding_rate          — giá trị mới nhất (số thập phân, e.g. 0.00005127)
      funding_rate_abs      — |funding_rate| (độ lớn bất kể chiều)
                              cao → thị trường mất cân bằng nghiêm trọng
      funding_bias          — +1 nếu LONG-heavy, -1 nếu SHORT-heavy, 0 nếu neutral
      funding_long_heavy    — bool: rate > +0.01%
      funding_short_heavy   — bool: rate < -0.01%
      funding_rate_change   — thay đổi so với lần cập nhật trước (delta 1h)
                              tăng mạnh → lệnh LONG đang tăng nhanh
                              giảm mạnh → lệnh SHORT đang tăng nhanh
      funding_trend_3h      — trung bình rate 3h gần nhất minus rate hiện tại
                              > 0 → xu hướng giảm dần (market rebalancing)
                              < 0 → xu hướng tăng dần (imbalance đang xây)
      secs_to_next_funding  — giây còn lại đến lần thanh toán tiếp theo
      funding_urgency       — 1 - (secs_to_next_funding / 28800)
                              → 0 vừa xong thanh toán, 1 sắp đến thanh toán
                              > 0.85 (~30 phút cuối) → trader đóng lệnh,
                                biến động tăng, spread có thể nới rộng
    """
    if df_funding.empty:
        return _empty_funding_features()

    df = df_funding.sort_values("timestamp").reset_index(drop=True)
    latest = df.iloc[-1]

    # ── Giá trị hiện tại ───────────────────────────────────
    funding_rate = float(latest["funding_rate"])
    funding_rate_abs = abs(funding_rate)

    if funding_rate > FUNDING_LONG_HEAVY:
        funding_bias = 1          # LONG-heavy
    elif funding_rate < FUNDING_SHORT_HEAVY:
        funding_bias = -1         # SHORT-heavy
    else:
        funding_bias = 0          # neutral

    funding_long_heavy  = bool(funding_rate > FUNDING_LONG_HEAVY)
    funding_short_heavy = bool(funding_rate < FUNDING_SHORT_HEAVY)

    # ── Delta so với lần cập nhật trước (≈1h trước) ────────
    funding_rate_change = None
    if len(df) >= 2:
        prev_rate = float(df.iloc[-2]["funding_rate"])
        funding_rate_change = funding_rate - prev_rate

    # ── Xu hướng 3h gần nhất ───────────────────────────────
    funding_trend_3h = None
    t_now  = df["timestamp"].max()
    t_3h   = t_now - pd.Timedelta(hours=3)
    df_3h  = df[df["timestamp"] >= t_3h]
    if len(df_3h) >= 2:
        avg_3h = float(df_3h["funding_rate"].mean())
        # Nếu avg > rate hiện tại → xu hướng đang giảm (tốt, market rebalancing)
        # Nếu avg < rate hiện tại → xu hướng đang tăng (imbalance tiếp tục xây)
        funding_trend_3h = avg_3h - funding_rate

    # ── Thời gian đến lần thanh toán tiếp theo ─────────────
    secs_to_next_funding = None
    funding_urgency      = None

    next_funding_raw = latest.get("next_funding_time")
    if pd.notna(next_funding_raw):
        try:
            # next_funding_time đã được parse thành UTC Timestamp bởi load_data.py
            # Không truyền tz= vì sẽ lỗi "Cannot pass tzinfo with the tz parameter"
            next_ts = pd.Timestamp(next_funding_raw)
            now_ts  = t_now  # đã là UTC từ load_funding_rate()

            delta_secs = (next_ts - now_ts).total_seconds()
            if delta_secs < 0:
                # Nếu đã qua, tính lần tiếp theo
                delta_secs += 8 * 3600

            secs_to_next_funding = int(delta_secs)
            # urgency: 0 = vừa xong thanh toán, ~1 = sắp đến
            funding_urgency = round(1.0 - (delta_secs / (8 * 3600)), 6)
            funding_urgency = max(0.0, min(1.0, funding_urgency))
        except Exception:
            pass

    return {
        "funding_rate":          round(funding_rate, 8),
        "funding_rate_abs":      round(funding_rate_abs, 8),
        "funding_bias":          funding_bias,
        "funding_long_heavy":    funding_long_heavy,
        "funding_short_heavy":   funding_short_heavy,
        "funding_rate_change":   round(funding_rate_change, 8) if funding_rate_change is not None else None,
        "funding_trend_3h":      round(funding_trend_3h, 8)    if funding_trend_3h    is not None else None,
        "secs_to_next_funding":  secs_to_next_funding,
        "funding_urgency":       funding_urgency,
    }


def _empty_funding_features() -> dict:
    return {
        "funding_rate":          None,
        "funding_rate_abs":      None,
        "funding_bias":          None,
        "funding_long_heavy":    None,
        "funding_short_heavy":   None,
        "funding_rate_change":   None,
        "funding_trend_3h":      None,
        "secs_to_next_funding":  None,
        "funding_urgency":       None,
    }