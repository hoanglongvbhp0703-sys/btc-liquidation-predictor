"""
debug_check.py — Chạy 1 lần để tìm nguyên nhân features = None

Chạy: python feature_engine/debug_check.py
"""

import pandas as pd
from pathlib import Path
from datetime import timedelta

DATA_DIR = Path(__file__).parent.parent / "data"

def check_file(name: str, time_col: str):
    path = DATA_DIR / name
    print(f"\n── {name} ──────────────────────────────")

    if not path.exists():
        print(f"  ❌ FILE KHÔNG TỒN TẠI: {path}")
        return

    df = pd.read_csv(path, header=0)
    print(f"  Tổng dòng     : {len(df)}")

    if df.empty:
        print("  ❌ FILE RỖNG")
        return

    # Parse timestamp
    try:
        df[time_col] = pd.to_datetime(df[time_col], format="ISO8601", utc=True)
    except Exception as e:
        print(f"  ❌ Lỗi parse timestamp: {e}")
        return

    t_min = df[time_col].min()
    t_max = df[time_col].max()
    print(f"  Timestamp đầu : {t_min}")
    print(f"  Timestamp cuối: {t_max}")

    # Kiểm tra khoảng cách so với now
    now = pd.Timestamp.now(tz="UTC")
    lag = (now - t_max).total_seconds()
    print(f"  Lag so với now: {lag:.0f}s {'⚠️  COLLECTOR CÓ THỂ ĐÃ DỪNG' if lag > 120 else '✅'}")

    # Kiểm tra filter since=5m
    since_5m = now.floor("5min") - timedelta(minutes=5)
    df_filtered = df[df[time_col] >= since_5m]
    print(f"  Since filter  : {since_5m}")
    print(f"  Dòng sau filter: {len(df_filtered)} {'❌ RỖNG SAU FILTER' if df_filtered.empty else '✅'}")

    if df_filtered.empty and not df.empty:
        print(f"  ⚠️  Dữ liệu cuối cùng cách now {lag:.0f}s — since filter cắt hết dữ liệu")
        print(f"     → Kiểm tra collector có đang chạy không")


def main():
    now = pd.Timestamp.now(tz="UTC")
    print(f"Now UTC       : {now}")
    print(f"now.floor(5m) : {now.floor('5min')}")
    print(f"since (ago_5m): {now.floor('5min') - timedelta(minutes=5)}")

    check_file("klines_1s.csv",      "open_time")
    check_file("liquidations.csv",   "event_time")
    check_file("orderbook.csv",      "timestamp")
    check_file("aggtrades.csv",      "timestamp")
    check_file("open_interest.csv",  "timestamp")
    check_file("funding_rate.csv",   "timestamp")

    print("\n──────────────────────────────────────────")
    print("Kết luận:")
    print("  - Lag > 120s  → collector đã dừng, cần restart tầng 1")
    print("  - Rỗng sau filter nhưng có data → since filter quá hẹp")
    print("  - File không tồn tại → collector chưa bao giờ ghi file này")


if __name__ == "__main__":
    main()