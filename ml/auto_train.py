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

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FEATURES_FILE, META_FILE, TRAIN_HISTORY_FILE, MIN_ROWS_TRAIN

HISTORY_FILE     = TRAIN_HISTORY_FILE
MIN_LABELED      = MIN_ROWS_TRAIN
INTERVAL         = 3600   # 1 giờ
PATIENCE         = 3      # dừng nếu không cải thiện 3 lần liên tiếp
MIN_DELTA        = 0.001  # cải thiện tối thiểu để tính là "tốt hơn"


def count_labeled_rows() -> int:
    if not FEATURES_FILE.exists():
        return 0
    df = pd.read_csv(FEATURES_FILE)
    if "label" not in df.columns:
        return 0
    return int(df["label"].isin([0, 1]).sum())


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
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {"runs": [], "stable": False}


def save_history(history: dict):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
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
    no_improvement = (latest - best_prev) < MIN_DELTA
    if no_improvement:
        print(f"[AUTO-TRAIN] AUC {PATIENCE} lần gần nhất: {recent}", flush=True)
        print(f"[AUTO-TRAIN] Không cải thiện >= {MIN_DELTA} — model đã ổn định.", flush=True)
    return no_improvement


def main():
    history = load_history()

    if history.get("stable"):
        auc = history["runs"][-1].get("auc") if history["runs"] else "?"
        print(f"[AUTO-TRAIN] Model đã ổn định (AUC={auc}). Không train thêm.", flush=True)
        print(f"[AUTO-TRAIN] Xem lịch sử: {HISTORY_FILE}", flush=True)
        return

    print(f"[AUTO-TRAIN] Khởi động — check mỗi {INTERVAL//60} phút, dừng sau {PATIENCE} lần không cải thiện.", flush=True)

    while True:
        n = count_labeled_rows()
        print(f"[AUTO-TRAIN] Labeled rows: {n}/{MIN_LABELED}", flush=True)

        if n >= MIN_LABELED:
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
                    history["stable"] = True
                    save_history(history)
                    print(f"[AUTO-TRAIN] Dừng auto-train. Model lưu tại ml/artifacts/", flush=True)
                    return

                save_history(history)
        else:
            print(f"[AUTO-TRAIN] Chưa đủ data, cần thêm {MIN_LABELED - n} rows.", flush=True)

        print(f"[AUTO-TRAIN] Chờ {INTERVAL//60} phút...", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
