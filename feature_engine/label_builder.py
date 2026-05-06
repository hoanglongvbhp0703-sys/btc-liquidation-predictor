"""
label_builder.py — Tầng 3: Xây dựng label cho features_5m.csv

Logic:
  Tại thời điểm T (đã có features):
    label = 1  nếu max(high) trong [T, T+30m] >= liq_zone_upper
    label = 0  nếu không

  Chỉ xử lý các row:
    - label còn trống ("")
    - timestamp <= now - 30 phút (đã đủ dữ liệu nhìn lại)
    - liq_zone_upper không null

Mã label đặc biệt:
  -1 = liq_zone_upper là null/NaN (không thể label)
  -2 = không đủ kline data trong cửa sổ 30p

Gọi từ run.py sau mỗi lần build_feature_row().
"""

import pandas as pd
from pathlib import Path
from datetime import timedelta

FEATURES_FILE = Path(__file__).parent.parent / "data" / "features_5m.csv"
KLINES_FILE   = Path(__file__).parent.parent / "data" / "klines_1s.csv"

LABEL_DELAY = timedelta(minutes=30)
MIN_KLINES  = 5   # ít nhất 5 kline rows trong cửa sổ 30 phút


def _load_klines_for_range(t_start: pd.Timestamp, t_end: pd.Timestamp) -> pd.DataFrame:
    """
    Load klines_1s.csv chỉ trong khoảng [t_start, t_end].
    Dùng usecols để chỉ đọc 2 cột cần thiết, tránh load toàn bộ file
    khi klines_1s.csv đã có hàng triệu rows (30 ngày = ~2.5M rows).
    """
    df = pd.read_csv(
        KLINES_FILE,
        names=["open_time", "open", "high", "low", "close",
               "volume", "taker_buy_vol", "num_trades"],
        header=0,
        dtype={"high": float},
        usecols=["open_time", "high"],
    )
    df["open_time"] = pd.to_datetime(
        df["open_time"], format="ISO8601", utc=True, errors="coerce"
    )
    df = df.dropna(subset=["open_time"])
    return df[(df["open_time"] >= t_start) & (df["open_time"] <= t_end)].reset_index(drop=True)


def build_pending_labels() -> int:
    """
    Duyệt features_5m.csv, điền label cho các row đã đủ 30 phút.
    Returns: số row được điền label (0 hoặc 1) trong lần chạy này.
    """
    if not FEATURES_FILE.exists():
        print("[LB] features_5m.csv chưa tồn tại, bỏ qua.")
        return 0

    df_feat = pd.read_csv(FEATURES_FILE, dtype={"label": str})

    pending_mask = (
        df_feat["label"].isna() |
        (df_feat["label"].astype(str).str.strip() == "")
    )
    pending_idx = df_feat[pending_mask].index.tolist()

    if not pending_idx:
        return 0

    if not KLINES_FILE.exists():
        print("[LB] klines_1s.csv chưa tồn tại, bỏ qua.")
        return 0

    now_utc = pd.Timestamp.now(tz="UTC")

    # Tính range klines cần load — chỉ load đúng khoảng thời gian cần thiết
    ts_series = pd.to_datetime(
        df_feat.loc[pending_idx, "timestamp"], format="ISO8601", utc=True, errors="coerce"
    ).dropna()

    if ts_series.empty:
        return 0

    kline_range_start = ts_series.min()
    kline_range_end   = ts_series.max() + LABEL_DELAY

    df_klines = _load_klines_for_range(kline_range_start, kline_range_end)

    labeled = 0
    skipped = 0

    for idx in pending_idx:
        row = df_feat.loc[idx]

        try:
            t_start = pd.Timestamp(row["timestamp"], tz="UTC")
        except Exception:
            continue

        t_end = t_start + LABEL_DELAY

        if t_end > now_utc:
            skipped += 1
            continue

        # liq_zone_upper null/NaN → không có ngưỡng
        liq_zone_upper = row.get("liq_zone_upper")
        try:
            liq_zone_upper = float(liq_zone_upper)
            if pd.isna(liq_zone_upper):
                raise ValueError("NaN")
        except (TypeError, ValueError):
            df_feat.at[idx, "label"] = -1
            continue

        klines_window = df_klines[
            (df_klines["open_time"] >= t_start) &
            (df_klines["open_time"] <= t_end)
        ]

        if len(klines_window) < MIN_KLINES:
            df_feat.at[idx, "label"] = -2
            continue

        max_high = float(klines_window["high"].max())
        label    = 1 if max_high >= liq_zone_upper else 0

        df_feat.at[idx, "label"] = label
        labeled += 1

    if labeled > 0 or skipped < len(pending_idx):
        df_feat.to_csv(FEATURES_FILE, index=False)

    total_labeled  = (df_feat["label"].astype(str).str.match(r"^[01]$")).sum()
    total_positive = (df_feat["label"].astype(str) == "1").sum()
    base_rate      = total_positive / total_labeled if total_labeled > 0 else 0.0

    print(
        f"[LB] Điền label: +{labeled} | "
        f"Chưa đủ 30p: {skipped} | "
        f"Tổng labeled: {total_labeled} | "
        f"Base rate: {base_rate:.1%}"
    )

    return labeled


def label_summary() -> dict:
    """Thống kê trạng thái label. Gọi thủ công để kiểm tra chất lượng data."""
    if not FEATURES_FILE.exists():
        return {}

    df = pd.read_csv(FEATURES_FILE, dtype={"label": str})
    lbl = df["label"].astype(str)

    total     = len(df)
    labeled   = lbl.str.match(r"^[01]$").sum()
    pending   = lbl.str.strip().eq("").sum()
    positive  = lbl.eq("1").sum()
    negative  = lbl.eq("0").sum()
    no_zone   = lbl.eq("-1").sum()
    no_klines = lbl.eq("-2").sum()
    base_rate = positive / labeled if labeled > 0 else 0.0

    summary = {
        "total_rows":  total,
        "labeled":     int(labeled),
        "pending":     int(pending),
        "positive":    int(positive),
        "negative":    int(negative),
        "base_rate":   round(float(base_rate), 4),
        "no_liq_zone": int(no_zone),
        "no_klines":   int(no_klines),
    }

    print("\n── Label Summary ──────────────────────────")
    for k, v in summary.items():
        print(f"  {k:<14}: {v}")
    print("──────────────────────────────────────────\n")

    return summary


if __name__ == "__main__":
    build_pending_labels()
    label_summary()
