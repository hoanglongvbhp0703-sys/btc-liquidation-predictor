"""
run.py — Tầng 5: Signal Output (Cascade Liquidation)

Mỗi 1 phút:
  1. Đọc feature row mới nhất từ features_1m.csv
  2. Predict cascade probability + timing (Ensemble RF+LR+XGB)
  3. Nếu cascade_prob >= 0.70 AND time_to_cascade <= 2m → ghi paper trade
  4. Check outcome trades cũ
  5. In stats mỗi 1 giờ
"""

import json
import sys
import time
import traceback
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "ml"))

from predict   import load_model, predict_cascade_signal
from paper_log import log_signal, check_outcomes, print_stats, has_open_trade
from notifier  import notify_signal

from config import (
    FEATURES_FILE, ML_DIR, DATA_DIR,
    SIGNAL_THRESHOLD, MIN_ROWS_TRAIN, LIQ_FILTER_USD,
    SIGNAL_COOLDOWN, MAX_TTC,
)

MODEL_FILE    = ML_DIR / "ens_cascade_long_3m.pkl"
COOLDOWN_FILE = DATA_DIR / "signal_cooldown.json"
RUN_INTERVAL  = 10
STATS_EVERY   = 60

_last_model_mtime: float = 0.0
_last_signal_ts: dict = {"long": 0.0, "short": 0.0}  # cooldown per direction — persisted to disk


def _load_cooldown():
    """Đọc cooldown timestamps từ disk để giữ qua restart."""
    global _last_signal_ts
    try:
        if COOLDOWN_FILE.exists():
            data = json.loads(COOLDOWN_FILE.read_text())
            _last_signal_ts["long"]  = float(data.get("long",  0.0))
            _last_signal_ts["short"] = float(data.get("short", 0.0))
    except Exception:
        pass


def _save_cooldown():
    try:
        COOLDOWN_FILE.write_text(json.dumps(_last_signal_ts))
    except Exception:
        pass


def load_latest_feature_row() -> dict | None:
    if not FEATURES_FILE.exists():
        print("[SIG] features_1m.csv chưa có.")
        return None
    try:
        df = pd.read_csv(FEATURES_FILE, dtype=str)
        if df.empty:
            return None
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df.iloc[-1].to_dict()
    except Exception as e:
        print(f"[SIG] Lỗi đọc features_1m.csv: {e}")
        return None


def _to_float(val) -> float | None:
    try:
        v = float(val)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None


def _model_mtime() -> float:
    try:
        return MODEL_FILE.stat().st_mtime if MODEL_FILE.exists() else 0.0
    except OSError:
        return 0.0


def run_once(model_ctx: dict | None, cycle: int) -> dict | None:
    global _last_model_mtime
    now = pd.Timestamp.now(tz="UTC")
    print(f"\n[SIG] ── {now.strftime('%Y-%m-%d %H:%M')} UTC ──")

    current_mtime = _model_mtime()
    if MODEL_FILE.exists() and (model_ctx is None or current_mtime > _last_model_mtime):
        try:
            model_ctx = load_model()
            _last_model_mtime = current_mtime
            print(f"[SIG] Model {'re' if _last_model_mtime else ''}loaded | avg_auc={model_ctx['meta'].get('avg_auc_test')}")
        except Exception as e:
            print(f"[SIG] Load model lỗi: {e}")
    elif model_ctx is None:
        n = _count_labeled_rows()
        print(f"[SIG] Model chưa train. cascade_long_3m labeled: {n} (cần {MIN_ROWS_TRAIN}+)")

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

    # Liq filter: bỏ qua nếu tổng thanh lý 1m < ngưỡng (cascade nhỏ không đáng trade)
    liq_total = _to_float(feature_row.get("liq_total_1m"))
    if liq_total is not None and liq_total < LIQ_FILTER_USD:
        print(f"[SIG] Liq filter: liq_total_1m={liq_total:,.0f} < {LIQ_FILTER_USD:,.0f} → skip")
        return model_ctx

    try:
        signal = predict_cascade_signal(model_ctx, feature_row, current_price, max_ttc=MAX_TTC)
    except Exception as e:
        print(f"[SIG] predict_cascade_signal lỗi: {e}")
        traceback.print_exc()
        return model_ctx

    if signal:
        direction = signal["direction"]
        now_epoch = pd.Timestamp.now(tz="UTC").timestamp()
        elapsed   = now_epoch - _last_signal_ts[direction]

        if has_open_trade(direction):
            print(f"[SIG] {direction.upper()} signal bỏ qua — đang có trade mở cùng chiều")
        elif elapsed < SIGNAL_COOLDOWN:
            remain = int(SIGNAL_COOLDOWN - elapsed)
            print(f"[SIG] {direction.upper()} signal bỏ qua — cooldown còn {remain}s")
        else:
            opened_at = pd.Timestamp.now(tz="UTC")
            log_signal(signal, opened_at)
            notify_signal(signal, opened_at)
            _last_signal_ts[direction] = now_epoch
            _save_cooldown()
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
║   Chạy mỗi 10 giây                         ║
╚══════════════════════════════════════════════╝
    """)

    _load_cooldown()
    print(f"[SIG] Cooldown restored — long={_last_signal_ts['long']:.0f}, short={_last_signal_ts['short']:.0f}")

    model_ctx = None
    cycle     = 0
    model_ctx = run_once(model_ctx, cycle)

    while True:
        time.sleep(RUN_INTERVAL)
        cycle    += 1
        model_ctx = run_once(model_ctx, cycle)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[SIG] Đã dừng.")
        print_stats()
