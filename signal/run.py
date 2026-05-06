"""
run.py — Tầng 5: Signal Output

Chạy song song với feature_engine/run.py (cùng mốc 5 phút):
    python signal/run.py

Mỗi chu kỳ 5 phút:
  1. Đọc feature row mới nhất từ features_5m.csv
  2. Nếu model chưa train (saved/ trống) → bỏ qua, thông báo
  3. Predict signal với model XGBoost
  4. Nếu có signal LONG:
       → ghi paper_log
       → gửi Telegram
  5. Check outcome của paper trades cũ (đủ 30 phút chưa?)
  6. In stats mỗi 1 giờ (12 chu kỳ)

Phụ thuộc:
  - model/saved/ phải có xgb_model.json (chạy model/train.py trước)
  - data/features_5m.csv phải đang được cập nhật bởi feature_engine/run.py
"""

import sys
import time
import traceback
from pathlib import Path

import pandas as pd

# ─── Thêm thư mục gốc vào sys.path để import ml/ ───────────────
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "ml"))

from predict   import load_model, predict_signal   # noqa: E402
from paper_log import log_signal, check_outcomes, print_stats   # noqa: E402
from notifier  import notify_signal   # noqa: E402

FEATURES_FILE = ROOT_DIR / "data" / "processed" / "features_5m.csv"
RUN_INTERVAL  = 300   # 5 phút
STATS_EVERY   = 12    # in stats mỗi 12 chu kỳ = 1 giờ


def load_latest_feature_row() -> dict | None:
    """
    Đọc row mới nhất từ features_5m.csv.
    Bỏ qua row có label đã điền (dùng row mới nhất chưa bị điền label
    hoặc row cuối cùng nếu tất cả đã có label).
    """
    if not FEATURES_FILE.exists():
        print("[SIG] ⚠️  features_5m.csv chưa có — feature_engine/run.py đang chạy chưa?")
        return None

    try:
        df = pd.read_csv(FEATURES_FILE, dtype=str)
        if df.empty:
            print("[SIG] ⚠️  features_5m.csv trống.")
            return None

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

        row = df.iloc[-1].to_dict()
        return row

    except Exception as e:
        print(f"[SIG] ❌ Lỗi đọc features_5m.csv: {e}")
        return None


def _to_float(val) -> float | None:
    try:
        v = float(val)
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return None


def run_once(model_ctx: dict | None, cycle: int) -> dict | None:
    """
    Chạy 1 chu kỳ predict + check outcomes.
    Trả về model_ctx (có thể reload nếu model mới được train).
    """
    now = pd.Timestamp.now(tz="UTC")
    print(f"\n[SIG] ── {now.strftime('%Y-%m-%d %H:%M')} UTC ──")

    # ── (Re)load model nếu chưa có hoặc model file mới hơn ────────
    model_file = ROOT_DIR / "model" / "saved" / "xgb_model.json"

    if model_ctx is None:
        if model_file.exists():
            try:
                model_ctx = load_model()
                print(f"[SIG] ✅ Model loaded | AUC_test={model_ctx['meta'].get('auc_test')}")
            except Exception as e:
                print(f"[SIG] ❌ Load model thất bại: {e}")
        else:
            labeled_count = _count_labeled_rows()
            print(
                f"[SIG] ⏳ Model chưa train. "
                f"Đang tích lũy labeled data: {labeled_count} rows "
                f"(cần ít nhất 200, khuyến nghị 2000+).\n"
                f"       Khi đủ data: python model/train.py"
            )

    # ── Check outcome paper trades cũ ─────────────────────────────
    try:
        n_closed = check_outcomes()
        if n_closed > 0:
            print(f"[SIG] 🔔 Đã đóng {n_closed} paper trade(s)")
    except Exception as e:
        print(f"[SIG] ❌ Lỗi check_outcomes: {e}")
        traceback.print_exc()

    # ── Predict signal ─────────────────────────────────────────────
    if model_ctx is None:
        return model_ctx  # chưa có model, bỏ qua predict

    feature_row = load_latest_feature_row()
    if feature_row is None:
        return model_ctx

    current_price   = _to_float(feature_row.get("current_price"))
    liq_zone_upper  = _to_float(feature_row.get("liq_zone_upper"))
    liq_zone_lower  = _to_float(feature_row.get("liq_zone_lower"))

    if current_price is None:
        print("[SIG] ⚠️  current_price không hợp lệ trong feature row mới nhất.")
        return model_ctx

    try:
        signal = predict_signal(
            model_ctx,
            feature_row,
            current_price,
            liq_zone_upper,
            liq_zone_lower,
        )
    except Exception as e:
        print(f"[SIG] ❌ Lỗi predict_signal: {e}")
        traceback.print_exc()
        return model_ctx

    if signal:
        opened_at = pd.Timestamp.now(tz="UTC")
        log_signal(signal, opened_at)
        notify_signal(signal, opened_at)
    else:
        prob_hint = ""
        try:
            from model.predict import predict_proba
            prob = predict_proba(model_ctx, feature_row)
            prob_hint = f" (prob={prob:.3f}, threshold={model_ctx['threshold']})"
        except Exception:
            pass
        print(f"[SIG] ─ Không có signal{prob_hint}")

    # ── In stats mỗi STATS_EVERY chu kỳ ──────────────────────────
    if cycle % STATS_EVERY == 0:
        try:
            print_stats()
        except Exception:
            pass

    return model_ctx


def _count_labeled_rows() -> int:
    try:
        df = pd.read_csv(FEATURES_FILE, dtype={"label": str})
        return int(df["label"].astype(str).str.match(r"^[01]$").sum())
    except Exception:
        return 0


def main():
    print("""
╔══════════════════════════════════════════════╗
║   BTC Signal Output — Tầng 5               ║
║   Chạy mỗi 5 phút                          ║
╚══════════════════════════════════════════════╝
    """)

    model_ctx = None
    cycle     = 0

    # Chạy ngay lần đầu
    model_ctx = run_once(model_ctx, cycle)

    while True:
        now      = pd.Timestamp.now(tz="UTC")
        next_run = (now + pd.Timedelta(minutes=5)).floor("5min")
        sleep_s  = (next_run - now).total_seconds()

        print(f"[SIG] ⏳ Chờ đến {next_run.strftime('%H:%M')} UTC ({sleep_s:.0f}s)...")
        time.sleep(max(sleep_s, 1))

        cycle    += 1
        model_ctx = run_once(model_ctx, cycle)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[SIG] Đã dừng bởi người dùng.")
        print_stats()
