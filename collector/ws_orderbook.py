"""
ws_orderbook.py — WebSocket Order Book Depth Binance Futures

Fix quan trọng nhất:
  STREAM URL SAI → đúng phải là /stream?streams= không phải /market/ws/
  Sai:  wss://fstream.binance.com/market/ws/btcusdt@depth20@500ms
  Đúng: wss://fstream.binance.com/stream?streams=btcusdt@depth20@500ms

  Khi dùng /stream?streams=, Binance wrap data trong:
    {"stream": "btcusdt@depth20@500ms", "data": {"b": [...], "a": [...], ...}}
  Nên phải đọc msg["data"] thay vì msg trực tiếp.

Các fix khác:
  - Dùng dict state thay nonlocal để tránh closure stale khi reconnect
  - writer_task định nghĩa 1 lần bên ngoài vòng reconnect
  - Index tuyệt đối (row[21..25]) thay vì index âm
  - Log lỗi rõ ràng, không bao giờ crash âm thầm
"""

import json
import asyncio
import sys
import websockets
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SYMBOL

from db import (
    append_csv, now_utc,
    init_csv_files, get_pool,
    insert_orderbook
)

# ─── Cấu hình ──────────────────────────────────────────────────
# /stream?streams= là endpoint đúng cho depth stream
STREAM_URL      = f"wss://fstream.binance.com/stream?streams={SYMBOL.lower()}@depth20@500ms"
RECONNECT_DELAY = 5
MAX_RECONNECT   = 999
WRITE_INTERVAL  = 1.0
TOP_N_LEVELS    = 5


def extract_bids_asks(msg: dict) -> tuple:
    """
    Khi dùng /stream?streams=, Binance wrap data:
      {"stream": "btcusdt@depth20@500ms", "data": {"b": [...], "a": [...], ...}}

    Fallback thêm format direct phòng trường hợp Binance thay đổi.
    """
    # Format chuẩn khi dùng /stream?streams=
    data = msg.get("data", {})
    if "b" in data and "a" in data:
        return data["b"], data["a"]

    # Fallback: format direct (không có wrapper)
    if "b" in msg and "a" in msg:
        return msg["b"], msg["a"]

    return None, None


def compute_features(bids: list, asks: list) -> dict:
    bid1 = Decimal(bids[0][0])
    ask1 = Decimal(asks[0][0])

    mid_price     = (bid1 + ask1) / 2
    spread        = ask1 - bid1
    bid_vol_total = sum(Decimal(b[1]) for b in bids[:TOP_N_LEVELS])
    ask_vol_total = sum(Decimal(a[1]) for a in asks[:TOP_N_LEVELS])
    total_vol     = bid_vol_total + ask_vol_total
    imbalance     = bid_vol_total / total_vol if total_vol > 0 else Decimal("0.5")

    return {
        "mid_price":      mid_price,
        "spread":         spread,
        "bid_vol_total":  bid_vol_total,
        "ask_vol_total":  ask_vol_total,
        "imbalance":      imbalance,
    }


def build_row(bids: list, asks: list) -> list:
    while len(bids) < TOP_N_LEVELS:
        bids.append(["0", "0"])
    while len(asks) < TOP_N_LEVELS:
        asks.append(["0", "0"])

    features = compute_features(bids, asks)
    ts = now_utc().isoformat()

    row = [ts]
    for i in range(TOP_N_LEVELS):
        row.append(str(bids[i][0]))  # price
        row.append(str(bids[i][1]))  # qty
    for i in range(TOP_N_LEVELS):
        row.append(str(asks[i][0]))
        row.append(str(asks[i][1]))

    # index tuyệt đối:
    # [21] mid_price  [22] spread  [23] bid_vol_total  [24] ask_vol_total  [25] imbalance
    row.append(str(features["mid_price"]))
    row.append(str(features["spread"]))
    row.append(str(features["bid_vol_total"]))
    row.append(str(features["ask_vol_total"]))
    row.append(str(features["imbalance"]))

    return row


async def run_orderbook_stream():
    print(f"[OB] Kết nối tới: {STREAM_URL}")
    pool = None
    try:
        pool = await get_pool()
    except Exception:
        pass

    # Dict mutable — tránh hoàn toàn vấn đề nonlocal/closure stale
    state = {
        "latest_bids": None,
        "latest_asks": None,
    }

    async def writer_task():
        """Ghi CSV mỗi WRITE_INTERVAL giây, độc lập với WebSocket loop."""
        while True:
            await asyncio.sleep(WRITE_INTERVAL)

            if state["latest_bids"] is None:
                continue

            bids = state["latest_bids"]
            asks = state["latest_asks"]
            state["latest_bids"] = None
            state["latest_asks"] = None

            try:
                row = build_row(bids, asks)
                append_csv("orderbook", row)

                mid_price = row[21]
                spread    = row[22]
                imbalance = float(row[25])

                side = (
                    "🟢 BUY " if imbalance > 0.55
                    else "🔴 SELL" if imbalance < 0.45
                    else "⚪ NEU "
                )
                print(
                    f"[OB] Mid: {mid_price} | Spread: {spread} | "
                    f"Imb: {imbalance:.3f} {side}"
                )

                if pool:
                    await insert_orderbook(pool, row)

            except Exception as e:
                print(f"[OB] ❌ Lỗi write row: {e}")

    attempt = 0
    while attempt < MAX_RECONNECT:
        try:
            async with websockets.connect(
                STREAM_URL,
                ping_interval=20,
                ping_timeout=30,
                close_timeout=10
            ) as ws:
                print(f"[OB] ✅ Đã kết nối. Ghi CSV mỗi {WRITE_INTERVAL}s...")
                attempt = 0
                state["latest_bids"] = None
                state["latest_asks"] = None

                writer = asyncio.create_task(writer_task())

                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        bids, asks = extract_bids_asks(msg)
                        if bids is not None and asks is not None:
                            state["latest_bids"] = bids
                            state["latest_asks"] = asks
                finally:
                    writer.cancel()
                    await asyncio.gather(writer, return_exceptions=True)

        except (websockets.exceptions.ConnectionClosed, Exception) as e:
            attempt += 1
            print(
                f"[OB] ⚠️  Mất kết nối: {e}. "
                f"Thử lại {attempt}/{MAX_RECONNECT} sau {RECONNECT_DELAY}s..."
            )
            await asyncio.sleep(RECONNECT_DELAY)

    print("[OB] ❌ Vượt quá số lần reconnect tối đa")


if __name__ == "__main__":
    init_csv_files()
    try:
        asyncio.run(run_orderbook_stream())
    except KeyboardInterrupt:
        print("\n[OB] Đã dừng bởi người dùng.")