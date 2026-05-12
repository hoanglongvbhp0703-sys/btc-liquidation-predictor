"""
run.py — Tầng 5: Signal Output (Cascade Liquidation)

Mỗi 5 phút:
  1. Đọc feature row mới nhất từ features_5m.csv
  2. Predict cascade probability + timing
  3. Nếu cascade_prob >= 0.70 AND time_to_cascade <= 15m → ghi paper trade
  4. Check outcome trades cũ
  5. In stats mỗi 1 giờ
"""

import sys
import time
import traceback
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "ml"))

from predict   import load_model, predict_cascade_signal
from paper_log import log_signal, check_outcomes, print_stats
from notifier  import notify_signal

from config import FEATURES_FILE, ML_DIR, SIGNAL_THRESHOLD, MIN_ROWS_TRAIN

MODEL_FILE    = ML_DIR / "lgb_cascade_long_3m.pkl"
RUN_INTERVAL  = 60
STATS_EVERY   = 60
MAX_TTC       = 2.0    # chỉ trade khi cascade dự đoán <= 2 phút


def load_latest_feature_row() -> dict | None:
    if not FEATURES_FILE.exists():
        print("[SIG] features_5m.csv chưa có.")
        return None
    try:
        df = pd.read_csv(FEATURES_FILE, dtype=str)
        if df.empty:
            return None
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df.iloc[-1].to_dict()
    except Exception as e:
        print(f"[SIG] Lỗi đọc features_5m.csv: {e}")
        return None


def _to_float(val) -> float | None:
    try:
        v = float(val)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None


def run_once(model_ctx: dict | None, cycle: int) -> dict | None:
    now = pd.Timestamp.now(tz="UTC")
    print(f"\n[SIG] ── {now.strftime('%Y-%m-%d %H:%M')} UTC ──")

    if model_ctx is None:
        if MODEL_FILE.exists():
            try:
                model_ctx = load_model()
                print(f"[SIG] Model loaded | avg_auc={model_ctx['meta'].get('avg_auc_test')}")
            except Exception as e:
                print(f"[SIG] Load model lỗi: {e}")
        else:
            n = _count_labeled_rows()
            print(f"[SIG] Model chưa train. cascade_long_30m labeled: {n} (cần {MIN_ROWS_TRAIN}+)")

    try:
        n_closed = check_outcomes()
        if n_closed > 0:
            print(f"[SIG] Đóng {n_closed} paper trade(s)")
    except Exception as e:
        print(f"[SIG] check_outcomes lỗi: {e}")
        traceback.print_exc()

    if model_ctx is None:
        return model_ctx

    feature_row   = load_latest_feature_row()
    if feature_row is None:
        return model_ctx

    current_price = _to_float(feature_row.get("current_price"))
    if current_price is None:
        print("[SIG] current_price không hợp lệ.")
        return model_ctx

    try:
        signal = predict_cascade_signal(model_ctx, feature_row, current_price, max_ttc=MAX_TTC)
    except Exception as e:
        print(f"[SIG] predict_cascade_signal lỗi: {e}")
        traceback.print_exc()
        return model_ctx

    if signal:
        opened_at = pd.Timestamp.now(tz="UTC")
        log_signal(signal, opened_at)
        notify_signal(signal, opened_at)
    else:
        print(f"[SIG] Không có signal (threshold={SIGNAL_THRESHOLD}, max_ttc={MAX_TTC}m)")

    if cycle % STATS_EVERY == 0:
        try:
            print_stats()
        except Exception:
            pass

    return model_ctx


def _count_labeled_rows() -> int:
    try:
        df  = pd.read_csv(FEATURES_FILE)
        col = "cascade_long_3m" if "cascade_long_3m" in df.columns else "label"
        return int(pd.to_numeric(df[col], errors="coerce").isin([0, 1]).sum())
    except Exception:
        return 0


def main():
    print("""
╔══════════════════════════════════════════════╗
║   BTC Cascade Signal — Tầng 5              ║
║   Chạy mỗi 1 phút                          ║
╚══════════════════════════════════════════════╝
    """)

    model_ctx = None
    cycle     = 0
    model_ctx = run_once(model_ctx, cycle)

    while True:
        now      = pd.Timestamp.now(tz="UTC")
        next_run = (now + pd.Timedelta(minutes=1)).floor("1min")
        sleep_s  = (next_run - now).total_seconds()
        print(f"[SIG] Chờ đến {next_run.strftime('%H:%M')} UTC ({sleep_s:.0f}s)...")
        time.sleep(max(sleep_s, 1))
        cycle    += 1
        model_ctx = run_once(model_ctx, cycle)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[SIG] Đã dừng.")
        print_stats()
