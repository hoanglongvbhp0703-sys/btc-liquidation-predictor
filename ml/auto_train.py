"""
auto_train.py — Tự động retrain mỗi 1 giờ.

Dừng tự động khi AUC không cải thiện trong 3 lần train liên tiếp.
Lịch sử lưu tại: ml/artifacts/train_history.json
"""

import json
import time
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FEATURES_FILE, META_FILE, TRAIN_HISTORY_FILE, MIN_ROWS_TRAIN

INTERVAL  = 3600   # 1 giờ
PATIENCE  = 3      # dừng nếu không cải thiện 3 lần liên tiếp
MIN_DELTA = 0.001  # cải thiện tối thiểu để tính là "tốt hơn"


def count_labeled_rows() -> int:
    if not FEATURES_FILE.exists():
        return 0
    df  = pd.read_csv(FEATURES_FILE)
    col = "cascade_long_3m" if "cascade_long_3m" in df.columns else "label"
    if col not in df.columns:
        return 0
    return int(pd.to_numeric(df[col], errors="coerce").isin([0, 1]).sum())


def print_data_summary():
    """In tóm tắt dữ liệu gần nhất dùng để train."""
    if not FEATURES_FILE.exists():
        print("[AUTO-TRAIN] features_1m.csv chưa tồn tại.", flush=True)
        return
    df = pd.read_csv(FEATURES_FILE)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

    total     = len(df)
    col       = "cascade_long_3m" if "cascade_long_3m" in df.columns else "label"
    s         = pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.Series(dtype=float)
    labeled   = s.isin([0, 1]).sum()
    unlabeled = total - labeled
    pos       = (s == 1).sum()
    neg       = (s == 0).sum()
    first_ts   = df["timestamp"].iloc[0].strftime("%Y-%m-%d %H:%M") if total > 0 else "N/A"
    last_ts    = df["timestamp"].iloc[-1].strftime("%Y-%m-%d %H:%M") if total > 0 else "N/A"

    print(f"[AUTO-TRAIN] ── Dữ liệu hiện tại ──────────────────────────", flush=True)
    print(f"[AUTO-TRAIN]   Tổng rows    : {total}", flush=True)
    print(f"[AUTO-TRAIN]   Đã labeled   : {labeled}  (pos={pos}, neg={neg})", flush=True)
    print(f"[AUTO-TRAIN]   Chưa labeled : {unlabeled}  (chưa đủ 30 phút)", flush=True)
    print(f"[AUTO-TRAIN]   Từ           : {first_ts} UTC", flush=True)
    print(f"[AUTO-TRAIN]   Đến          : {last_ts} UTC", flush=True)
    print(f"[AUTO-TRAIN] ────────────────────────────────────────────────", flush=True)


def read_avg_auc() -> float | None:
    """Đọc AUC test trung bình của 12 models từ meta.json."""
    if not META_FILE.exists():
        return None
    with open(META_FILE) as f:
        meta = json.load(f)
    aucs = []
    for direction in ("long", "short"):
        for horizon_data in meta.get("horizons", {}).get(direction, {}).values():
            v = horizon_data.get("auc_test")
            if v is not None:
                aucs.append(v)
    return round(sum(aucs) / len(aucs), 4) if aucs else None


def load_history() -> dict:
    if TRAIN_HISTORY_FILE.exists():
        with open(TRAIN_HISTORY_FILE) as f:
            return json.load(f)
    return {"runs": [], "stable": False}


def save_history(history: dict):
    TRAIN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRAIN_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def run_train() -> bool:
    """Chạy train.py. Trả về True nếu thành công."""
    print("[AUTO-TRAIN] Bắt đầu train...", flush=True)
    result = subprocess.run(
        [sys.executable, Path(__file__).parent / "train.py"],
        capture_output=False,
    )
    ok = result.returncode == 0
    print(f"[AUTO-TRAIN] {'Train xong.' if ok else f'Train lỗi (code {result.returncode}).'}", flush=True)
    return ok


def check_stable(history: dict) -> bool:
    """Kiểm tra AUC có cải thiện trong PATIENCE lần gần nhất không."""
    runs = [r for r in history["runs"] if r.get("auc") is not None]
    if len(runs) < PATIENCE:
        return False
    recent = [r["auc"] for r in runs[-PATIENCE:]]
    best_prev = max(recent[:-1])
    latest = recent[-1]
    no_improvement = 0 <= (latest - best_prev) < MIN_DELTA
    if no_improvement:
        print(f"[AUTO-TRAIN] AUC {PATIENCE} lần gần nhất: {recent}", flush=True)
        print(f"[AUTO-TRAIN] Không cải thiện >= {MIN_DELTA} — model đã ổn định.", flush=True)
    return no_improvement


def main():
    history = load_history()
    # Không dừng hẳn khi stable — tiếp tục train để cải thiện khi có thêm data
    history["stable"] = False
    save_history(history)

    print(f"[AUTO-TRAIN] Khởi động — check mỗi {INTERVAL//60} phút.", flush=True)

    while True:
        print_data_summary()
        n = count_labeled_rows()
        print(f"[AUTO-TRAIN] Labeled rows: {n}/{MIN_ROWS_TRAIN}", flush=True)

        if n >= MIN_ROWS_TRAIN:
            ok = run_train()
            if ok:
                auc = read_avg_auc()
                run_record = {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "labeled_rows": n,
                    "auc": auc,
                }
                history["runs"].append(run_record)
                print(f"[AUTO-TRAIN] AUC trung bình: {auc}", flush=True)

                if check_stable(history):
                    print(f"[AUTO-TRAIN] AUC ổn định — tiếp tục train để cải thiện với data mới.", flush=True)

                save_history(history)
        else:
            print(f"[AUTO-TRAIN] Chưa đủ data, cần thêm {MIN_ROWS_TRAIN - n} rows.", flush=True)

        print(f"[AUTO-TRAIN] Chờ {INTERVAL//60} phút...", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
