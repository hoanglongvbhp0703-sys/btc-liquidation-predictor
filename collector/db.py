import os
import sys
import csv
import fcntl
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA_DIR, KLINES_FILE, LIQ_FILE, OI_FILE, FUNDING_FILE, ORDERBOOK_FILE, AGGTRADE_FILE

DATA_DIR.mkdir(exist_ok=True)

FILES = {
    "klines":      KLINES_FILE,
    "liquidation": LIQ_FILE,
    "oi":          OI_FILE,
    "funding":     FUNDING_FILE,
    "orderbook":   ORDERBOOK_FILE,
    "aggtrade":    AGGTRADE_FILE,
}

# ─── Định nghĩa Header ───────────────────────────────────────
CSV_HEADERS = {
    "klines": [
        "open_time", "open", "high", "low", "close",
        "volume", "taker_buy_vol", "num_trades"
    ],
    "liquidation": [
        "event_time", "symbol", "side",
        "price", "qty", "usd_value"
    ],
    "oi": [
        "timestamp", "oi_btc", "oi_usd"
    ],
    "funding": [
        "timestamp", "funding_rate", "next_funding_time"
    ],
    # Snapshot order book mỗi 1s:
    # bid/ask top 5 levels → đủ để tính imbalance, spread, wall
    "orderbook": [
        "timestamp",
        "bid1_price", "bid1_qty", "bid2_price", "bid2_qty",
        "bid3_price", "bid3_qty", "bid4_price", "bid4_qty",
        "bid5_price", "bid5_qty",
        "ask1_price", "ask1_qty", "ask2_price", "ask2_qty",
        "ask3_price", "ask3_qty", "ask4_price", "ask4_qty",
        "ask5_price", "ask5_qty",
        # Features tính sẵn để tiết kiệm thời gian lúc train
        "mid_price",      # (bid1 + ask1) / 2
        "spread",         # ask1 - bid1
        "bid_vol_total",  # tổng qty 5 bid levels
        "ask_vol_total",  # tổng qty 5 ask levels
        "imbalance",      # bid_vol / (bid_vol + ask_vol) → >0.5 = áp lực mua
    ],
    # Mỗi aggTrade là 1 lệnh khớp (gom nhiều lệnh nhỏ cùng giá/thời điểm)
    # Dùng để tính CVD (Cumulative Volume Delta)
    "aggtrade": [
        "timestamp",
        "agg_id",
        "price",
        "qty",
        "usd_value",
        "is_buyer_maker",  # True = bán chủ động, False = mua chủ động
        "cvd_delta",       # +qty nếu mua chủ động, -qty nếu bán chủ động
    ],
}

# ─── Khởi tạo file ──────────────────────────────────────────
def init_csv_files():
    """Tạo file CSV với header nếu chưa tồn tại."""
    for key, filepath in FILES.items():
        if not filepath.exists():
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADERS[key])
                f.flush()
                os.fsync(f.fileno())
            print(f"[CSV] Tạo file thành công: {filepath.name}")
        else:
            print(f"[CSV] File đã tồn tại: {filepath.name}")

# ─── Ghi dữ liệu (flush + fsync + file lock) ────────────────
def append_csv(key: str, row: list):
    """Ghi 1 dòng vào CSV với exclusive lock để tránh race condition."""
    filepath = FILES[key]
    try:
        needs_header = not filepath.exists() or filepath.stat().st_size == 0
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                writer = csv.writer(f)
                if needs_header:
                    writer.writerow(CSV_HEADERS[key])
                writer.writerow(row)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        print(f"[CSV-ERROR] Không thể ghi file {key}: {e}")

# ─── Mock DB Helpers ─────────────────────────────────────────
async def get_pool(): return None
async def close_pool(): pass
async def init_db(): print("[DB] Chế độ bypass: Chỉ sử dụng CSV.")
async def insert_kline(pool, row): pass
async def insert_liquidation(pool, row): pass
async def insert_oi(pool, row): pass
async def insert_funding(pool, row): pass
async def insert_orderbook(pool, row): pass
async def insert_aggtrade(pool, row): pass

# ─── Utility ────────────────────────────────────────────────
def ts_from_ms(ms: int) -> datetime:
    """Convert milliseconds timestamp → datetime UTC."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)