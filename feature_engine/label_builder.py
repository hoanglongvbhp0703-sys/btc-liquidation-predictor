"""
label_builder.py — Tầng 3: Xây dựng label cho features_5m.csv

Logic LONG (label_Xm):
  label_Xm = 1  nếu max(high) trong [T, T+Xm] >= liq_zone_upper
  label_Xm = 0  nếu không

Logic SHORT (label_short_Xm):
  label_short_Xm = 1  nếu min(low) trong [T, T+Xm] <= liq_zone_lower
  label_short_Xm = 0  nếu không

Alias backward compat:
  label       = label_30m
  label_short = label_short_30m

Mã đặc biệt:
  -1 = liq_zone_upper/lower là null/NaN
  -2 = không đủ kline data trong cửa sổ
"""

import pandas as pd
from pathlib import Path
from datetime import timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FEATURES_FILE, KLINES_FILE

HORIZONS   = [5, 10, 15, 20, 25, 30]
MIN_KLINES = 5


def _label_col(direction: str, minutes: int) -> str:
    """Tên cột label. label/label_short là alias cho 30m (backward compat)."""
    if direction == "long":
        return "label" if minutes == 30 else f"label_{minutes}m"
    return "label_short" if minutes == 30 else f"label_short_{minutes}m"


ALL_LABEL_COLS = [_label_col("long", h)  for h in HORIZONS] + \
                 [_label_col("short", h) for h in HORIZONS]


def _load_klines_for_range(t_start: pd.Timestamp, t_end: pd.Timestamp) -> pd.DataFrame:
    df = pd.read_csv(
        KLINES_FILE,
        names=["open_time", "open", "high", "low", "close",
               "volume", "taker_buy_vol", "num_trades"],
        header=0,
        dtype={"high": float, "low": float},
        usecols=["open_time", "high", "low"],
    )
    df["open_time"] = pd.to_datetime(
        df["open_time"], format="ISO8601", utc=True, errors="coerce"
    )
    df = df.dropna(subset=["open_time"])
    return df[(df["open_time"] >= t_start) & (df["open_time"] <= t_end)].reset_index(drop=True)


def _is_pending(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and pd.isna(val):
        return True
    return str(val).strip() == ""


def build_pending_labels() -> int:
    if not FEATURES_FILE.exists():
        print("[LB] features_5m.csv chưa tồn tại, bỏ qua.")
        return 0

    df_feat = pd.read_csv(FEATURES_FILE)

    for col in ALL_LABEL_COLS:
        if col not in df_feat.columns:
            df_feat[col] = ""

    # Xác định row nào còn pending bất kỳ horizon nào
    pending_mask = pd.Series(False, index=df_feat.index)
    for col in ALL_LABEL_COLS:
        pending_mask |= df_feat[col].apply(_is_pending)

    pending_idx = df_feat[pending_mask].index.tolist()

    if not pending_idx:
        return 0

    if not KLINES_FILE.exists():
        print("[LB] klines_1s.csv chưa tồn tại, bỏ qua.")
        return 0

    now_utc = pd.Timestamp.now(tz="UTC")
    max_delay = timedelta(minutes=max(HORIZONS))

    ts_series = pd.to_datetime(
        df_feat.loc[pending_idx, "timestamp"], format="ISO8601", utc=True, errors="coerce"
    ).dropna()

    if ts_series.empty:
        return 0

    df_klines = _load_klines_for_range(ts_series.min(), ts_series.max() + max_delay)

    labeled_30m = 0
    skipped     = 0

    for idx in pending_idx:
        row = df_feat.loc[idx]

        try:
            t_start = pd.Timestamp(row["timestamp"], tz="UTC")
        except Exception:
            continue

        # Liq zones
        liq_upper_valid = False
        liq_upper = None
        try:
            liq_upper = float(row.get("liq_zone_upper"))
            if not pd.isna(liq_upper):
                liq_upper_valid = True
        except (TypeError, ValueError):
            pass

        liq_lower_valid = False
        liq_lower = None
        try:
            liq_lower = float(row.get("liq_zone_lower"))
            if not pd.isna(liq_lower):
                liq_lower_valid = True
        except (TypeError, ValueError):
            pass

        # Klines cho toàn bộ max horizon
        klines_max = df_klines[
            (df_klines["open_time"] >= t_start) &
            (df_klines["open_time"] <= t_start + max_delay)
        ]

        row_skipped = True

        for h in HORIZONS:
            t_end_h    = t_start + timedelta(minutes=h)
            col_long   = _label_col("long",  h)
            col_short  = _label_col("short", h)
            need_long  = _is_pending(df_feat.at[idx, col_long])
            need_short = _is_pending(df_feat.at[idx, col_short])

            if not need_long and not need_short:
                continue

            if t_end_h > now_utc:
                skipped += 1
                continue

            row_skipped = False
            klines_h   = klines_max[klines_max["open_time"] <= t_end_h]
            no_klines  = len(klines_h) < MIN_KLINES

            if need_long:
                if not liq_upper_valid:
                    df_feat.at[idx, col_long] = -1
                elif no_klines:
                    df_feat.at[idx, col_long] = -2
                else:
                    max_high = float(klines_h["high"].max())
                    df_feat.at[idx, col_long] = 1 if max_high >= liq_upper else 0
                    if h == 30:
                        labeled_30m += 1

            if need_short:
                if not liq_lower_valid:
                    df_feat.at[idx, col_short] = -1
                elif no_klines:
                    df_feat.at[idx, col_short] = -2
                else:
                    min_low = float(klines_h["low"].min())
                    df_feat.at[idx, col_short] = 1 if min_low <= liq_lower else 0

    df_feat.to_csv(FEATURES_FILE, index=False)

    def _stats(col):
        s = df_feat[col].astype(str)
        labeled  = s.str.match(r"^[01]$").sum()
        positive = s.eq("1").sum()
        return labeled, positive

    long_labeled, long_pos = _stats("label")
    short_labeled, short_pos = _stats("label_short")
    long_br  = long_pos  / long_labeled  if long_labeled  > 0 else 0.0
    short_br = short_pos / short_labeled if short_labeled > 0 else 0.0

    print(
        f"[LB] LONG  +{labeled_30m} labeled (30m) | pending: {skipped} | "
        f"total: {long_labeled} | base rate: {long_br:.1%}\n"
        f"[LB] SHORT labeled: {short_labeled} | base rate: {short_br:.1%}"
    )

    return labeled_30m


def label_summary() -> dict:
    if not FEATURES_FILE.exists():
        return {}

    df = pd.read_csv(FEATURES_FILE)

    def _stats(col):
        if col not in df.columns:
            return {}
        s = df[col].astype(str)
        labeled  = s.str.match(r"^[01]$").sum()
        positive = s.eq("1").sum()
        return {
            "labeled":   int(labeled),
            "positive":  int(positive),
            "negative":  int(s.eq("0").sum()),
            "base_rate": round(positive / labeled, 4) if labeled > 0 else 0.0,
            "no_zone":   int(s.eq("-1").sum()),
            "no_klines": int(s.eq("-2").sum()),
        }

    summary = {"total_rows": len(df), "long": {}, "short": {}}
    print("\n── Label Summary ──────────────────────────")
    print(f"  total_rows : {summary['total_rows']}")

    for direction in ("long", "short"):
        print(f"\n  {direction.upper()}:")
        for h in HORIZONS:
            col = _label_col(direction, h)
            st  = _stats(col)
            summary[direction][f"{h}m"] = st
            labeled  = st.get("labeled", 0)
            base_rate = st.get("base_rate", 0.0)
            print(f"    {h:>2}m  labeled={labeled:>5}  base_rate={base_rate:.1%}")

    print("──────────────────────────────────────────\n")
    return summary


if __name__ == "__main__":
    build_pending_labels()
    label_summary()
