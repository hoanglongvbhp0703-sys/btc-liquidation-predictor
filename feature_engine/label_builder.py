"""
label_builder.py — Tầng 3: Build cascade liquidation labels

Cascade LONG (cascade_long_Xm):
  = 1 nếu sum(liq_short_usd[T→T+Xm]) > 3 × avg_liq_short_pm × X
  Ý nghĩa: SHORT bị liq nhiều → giá TĂNG → LONG trade opportunity

Cascade SHORT (cascade_short_Xm):
  = 1 nếu sum(liq_long_usd[T→T+Xm]) > 3 × avg_liq_long_pm × X
  Ý nghĩa: LONG bị liq nhiều → giá GIẢM → SHORT trade opportunity

liq_short_usd = usd_value where side == 'BUY'  (SHORT position bị liquidated)
liq_long_usd  = usd_value where side == 'SELL' (LONG position bị liquidated)

time_to_cascade_long/short:
  = first h ∈ {1, 2, 3} where cascade_hm == 1, else NaN
"""

import pandas as pd
from pathlib import Path
from datetime import timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FEATURES_FILE, LIQ_FILE

HORIZONS         = [1, 2, 3]
LOOKBACK_MINUTES = 30   # baseline từ 30 phút lịch sử

# Lookback mở rộng khi cửa sổ 30m không có liq (expanding windows)
_LOOKBACK_CHAIN = [
    30,    # phút — thử 30m trước
    120,   # thử 2h
    360,   # thử 6h
    1440,  # thử 24h
]


def _cascade_col(direction: str, minutes: int) -> str:
    return f"cascade_{direction}_{minutes}m"


ALL_LABEL_COLS = (
    [_cascade_col("long",  h) for h in HORIZONS] +
    [_cascade_col("short", h) for h in HORIZONS] +
    ["time_to_cascade_long", "time_to_cascade_short"]
)


def _compute_liq_baseline(df_liq: pd.DataFrame, t_start: pd.Timestamp) -> tuple[float, float]:
    """
    Tính per-minute baseline liq dùng expanding lookback.
    Thử 30m → 2h → 6h → 24h. Không dùng hardcoded floor.
    Trả về (avg_short_pm, avg_long_pm).
    """
    for lb_min in _LOOKBACK_CHAIN:
        t_lb   = t_start - timedelta(minutes=lb_min)
        hist   = df_liq[(df_liq["event_time"] >= t_lb) & (df_liq["event_time"] < t_start)]
        if hist.empty:
            continue
        n_min  = max((t_start - hist["event_time"].min()).total_seconds() / 60, 1.0)
        short  = hist["liq_short"].sum() / n_min
        long_  = hist["liq_long"].sum()  / n_min
        if short > 0 or long_ > 0:
            return short, long_

    # Toàn bộ dataset không có liq nào trước T — cực kỳ hiếm
    # Dùng global median thay vì hardcode
    n_min  = max((t_start - df_liq["event_time"].min()).total_seconds() / 60, 1.0) if not df_liq.empty else 1.0
    short  = df_liq["liq_short"].sum() / n_min if not df_liq.empty else 0.0
    long_  = df_liq["liq_long"].sum()  / n_min if not df_liq.empty else 0.0
    return max(short, 1.0), max(long_, 1.0)


def _is_pending(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and pd.isna(val):
        return True
    return str(val).strip() == ""


def _load_liq() -> pd.DataFrame:
    df = pd.read_csv(
        LIQ_FILE,
        usecols=["event_time", "side", "usd_value"],
        dtype={"usd_value": float},
    )
    df["event_time"] = pd.to_datetime(df["event_time"], utc=True, errors="coerce")
    df = df.dropna(subset=["event_time"]).sort_values("event_time")
    df["liq_short"] = df["usd_value"].where(df["side"] == "BUY",  0.0)
    df["liq_long"]  = df["usd_value"].where(df["side"] == "SELL", 0.0)
    return df


def build_pending_labels() -> int:
    if not FEATURES_FILE.exists():
        print("[LB] features_1m.csv chưa tồn tại.")
        return 0
    if not LIQ_FILE.exists():
        print("[LB] liquidations.csv chưa tồn tại.")
        return 0

    df_feat = pd.read_csv(FEATURES_FILE)
    for col in ALL_LABEL_COLS:
        if col not in df_feat.columns:
            df_feat[col] = ""

    pending_mask = pd.Series(False, index=df_feat.index)
    for col in ALL_LABEL_COLS:
        pending_mask |= df_feat[col].apply(_is_pending)

    pending_idx = df_feat[pending_mask].index.tolist()
    if not pending_idx:
        return 0

    df_liq      = _load_liq()
    now_utc     = pd.Timestamp.now(tz="UTC")
    max_horizon = timedelta(minutes=max(HORIZONS))

    labeled_count = 0
    skipped       = 0

    for idx in pending_idx:
        row = df_feat.loc[idx]
        try:
            t_start = pd.Timestamp(row["timestamp"], tz="UTC")
        except Exception:
            continue

        if t_start + max_horizon > now_utc:
            skipped += 1
            continue

        # Per-minute baseline từ expanding lookback (30m → 2h → 6h → 24h → global)
        avg_short_pm, avg_long_pm = _compute_liq_baseline(df_liq, t_start)

        # Forward liq [T, T+max_horizon)
        liq_fwd = df_liq[
            (df_liq["event_time"] >= t_start) &
            (df_liq["event_time"] <  t_start + max_horizon)
        ]

        ttc_long  = float("nan")
        ttc_short = float("nan")

        for h in HORIZONS:
            t_end = t_start + timedelta(minutes=h)
            liq_h = liq_fwd[liq_fwd["event_time"] < t_end]

            # cascade nếu rate trung bình trong cửa sổ h phút > 3× baseline per-minute
            c_long  = 1 if liq_h["liq_short"].sum() > 3 * avg_short_pm * h else 0
            c_short = 1 if liq_h["liq_long"].sum()  > 3 * avg_long_pm  * h else 0

            col_l = _cascade_col("long",  h)
            col_s = _cascade_col("short", h)
            if _is_pending(df_feat.at[idx, col_l]):
                df_feat.at[idx, col_l] = c_long
            if _is_pending(df_feat.at[idx, col_s]):
                df_feat.at[idx, col_s] = c_short

            if pd.isna(ttc_long)  and c_long  == 1:
                ttc_long  = float(h)
            if pd.isna(ttc_short) and c_short == 1:
                ttc_short = float(h)

        if _is_pending(df_feat.at[idx, "time_to_cascade_long"]):
            df_feat.at[idx, "time_to_cascade_long"]  = ttc_long
        if _is_pending(df_feat.at[idx, "time_to_cascade_short"]):
            df_feat.at[idx, "time_to_cascade_short"] = ttc_short

        labeled_count += 1

    df_feat.to_csv(FEATURES_FILE, index=False)

    for direction in ("long", "short"):
        for h in HORIZONS:
            col = _cascade_col(direction, h)
            s   = pd.to_numeric(df_feat[col], errors="coerce")
            n   = s.isin([0, 1]).sum()
            pos = (s == 1).sum()
            br  = pos / n if n > 0 else 0.0
            print(f"[LB] {col}: labeled={n}  pos={pos}  base_rate={br:.1%}")

    print(f"[LB] Labeled {labeled_count} rows this run | pending (too recent): {skipped}")
    return labeled_count


def label_summary() -> dict:
    if not FEATURES_FILE.exists():
        return {}
    df = pd.read_csv(FEATURES_FILE)
    summary = {"total_rows": len(df)}
    print(f"\n── Cascade Label Summary ──────────────────────")
    print(f"  total_rows: {len(df)}")
    for direction in ("long", "short"):
        print(f"\n  {direction.upper()} CASCADE:")
        for h in HORIZONS:
            col = _cascade_col(direction, h)
            if col not in df.columns:
                continue
            s   = pd.to_numeric(df[col], errors="coerce")
            n   = s.isin([0, 1]).sum()
            pos = (s == 1).sum()
            br  = pos / n if n > 0 else 0.0
            print(f"    {h:>2}m  labeled={n:>5}  base_rate={br:.1%}")
    return summary


if __name__ == "__main__":
    build_pending_labels()
    label_summary()
