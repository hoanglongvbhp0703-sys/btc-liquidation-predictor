"""
run.py — Entry point Tầng 2: Feature Engineering + Label Builder

Chạy: python feature_engine/run.py

Scheduler mỗi 5 phút:
  1. build_feature_row(now)  → append vào features_5m.csv
  2. build_pending_labels()  → điền label cho row đã đủ 30 phút

Cấu trúc thư mục output:
  data/
  └── features_5m.csv   ← file này được tạo và cập nhật ở đây
"""

import csv
import sys
import time
import traceback
from pathlib import Path
from datetime import timezone, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FEATURES_FILE
from build_features import build_feature_row, FEATURE_COLUMNS
from label_builder import build_pending_labels
RUN_INTERVAL   = 300  # 5 phút


def init_features_file():
    """Tạo features_5m.csv với header nếu chưa tồn tại hoặc đang rỗng."""
    needs_header = not FEATURES_FILE.exists() or FEATURES_FILE.stat().st_size == 0
    if needs_header:
        with open(FEATURES_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(FEATURE_COLUMNS)
        print(f"[FE] Tạo file: {FEATURES_FILE.name}")
    else:
        print(f"[FE] File đã tồn tại: {FEATURES_FILE.name}")


def append_feature_row(row: dict):
    """Append 1 row vào features_5m.csv."""
    with open(FEATURES_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FEATURE_COLUMNS, extrasaction="ignore")
        writer.writerow(row)


def run_once():
    """Chạy 1 lần: tính features + điền labels."""
    now = pd.Timestamp.now(tz="UTC").floor("5min")  # làm tròn xuống 5 phút

    print(f"\n[FE] ── {now.strftime('%Y-%m-%d %H:%M')} UTC ──")

    # 1. Tính features
    try:
        row = build_feature_row(at_time=now)
        append_feature_row(row)
        print(
            f"[FE] ✅ Features ghi xong | "
            f"price={row.get('current_price')} | "
            f"imb={row.get('imbalance_now')} | "
            f"cvd={row.get('cvd_delta_5m')} | "
            f"dist_upper={row.get('dist_to_upper')}"
        )
    except Exception as e:
        print(f"[FE] ❌ Lỗi build features: {e}")
        traceback.print_exc()

    # 2. Điền labels cho các row cũ
    try:
        build_pending_labels()
    except Exception as e:
        print(f"[FE] ❌ Lỗi build labels: {e}")
        traceback.print_exc()


def main():
    print("""
╔══════════════════════════════════════════════╗
║   BTC Feature Engine — Tầng 2               ║
║   Chạy mỗi 5 phút                           ║
╚══════════════════════════════════════════════╝
    """)

    init_features_file()

    # Chạy ngay lần đầu
    run_once()

    # Sau đó chờ đến mốc 5 phút tiếp theo
    while True:
        now        = pd.Timestamp.now(tz="UTC")
        next_run   = (now + pd.Timedelta(minutes=5)).floor("5min")
        sleep_secs = (next_run - now).total_seconds()

        print(f"[FE] ⏳ Chờ đến {next_run.strftime('%H:%M')} UTC ({sleep_secs:.0f}s)...")
        time.sleep(max(sleep_secs, 1))

        run_once()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[FE] Đã dừng bởi người dùng.")