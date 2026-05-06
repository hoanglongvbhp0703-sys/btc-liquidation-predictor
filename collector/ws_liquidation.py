"""
ws_liquidation.py — WebSocket Liquidation Binance Futures
Stream: wss://fstream.binance.com/market/ws/!forceOrder@arr

Giải thích side:
  BUY  = lệnh SHORT bị liquidate → sàn buộc MUA vào để đóng → giá bị đẩy LÊN
  SELL = lệnh LONG bị liquidate  → sàn buộc BÁN ra để đóng → giá bị đẩy XUỐNG
"""

import json
import asyncio
import websockets
from decimal import Decimal

from db import (
    get_pool, insert_liquidation, append_csv,
    ts_from_ms, init_csv_files
)

# ─── Config ──────────────────────────────────────────────────
# FIX: !forceOrder@arr thuộc /market endpoint (không phải /public)
# Xác nhận tại: https://developers.binance.com/docs/derivatives/
#   usds-margined-futures/websocket-market-streams/All-Market-Liquidation-Order-Streams
STREAM_URL      = "wss://fstream.binance.com/market/ws/!forceOrder@arr"
RECONNECT_DELAY = 5
MAX_RECONNECT   = 999

# Log tất cả lệnh >= ngưỡng này ra console
# Đặt thấp (10_000) để dễ xác nhận data đang chảy vào
LOG_THRESHOLD_USD = 10_000  # $10K


def parse_liquidation(msg: dict) -> dict | None:
    """
    Parse WebSocket message liquidation.

    Cấu trúc message từ Binance:
    {
      "e": "forceOrder",
      "E": 1568014460893,   ← event time (ms)
      "o": {
        "s": "BTCUSDT",     ← symbol
        "S": "SELL",        ← side (BUY hoặc SELL)
        "q": "0.014",       ← original quantity
        "p": "9910",        ← price
        "ap": "9910",       ← average fill price
        "X": "FILLED",      ← order status
        "T": 1568014460893  ← order trade time (ms)
      }
    }
    """
    try:
        o = msg.get("o", {})
        event_time = ts_from_ms(msg["E"])
        # Ưu tiên average price (ap), fallback về price (p)
        price     = Decimal(o["ap"]) if o.get("ap", "0") != "0" else Decimal(o["p"])
        qty       = Decimal(o["q"])
        usd_value = price * qty

        return {
            "event_time": event_time,
            "symbol":     o["s"],
            "side":       o["S"],
            "price":      price,
            "qty":        qty,
            "usd_value":  usd_value,
        }
    except (KeyError, Exception) as e:
        print(f"[LIQ] Parse error: {e} | msg: {msg}")
        return None


async def save_liquidation(pool, row: dict):
    """Lưu vào CSV và TimescaleDB."""
    append_csv("liquidation", [
        row["event_time"].isoformat(),
        row["symbol"],
        row["side"],
        str(row["price"]),
        str(row["qty"]),
        str(row["usd_value"]),
    ])

    if pool:
        try:
            await insert_liquidation(pool, row)
        except Exception as e:
            print(f"[LIQ] DB error: {e}")


async def run_liquidation_stream():
    """Stream liquidation toàn thị trường với auto-reconnect."""
    print(f"[LIQ] Bắt đầu stream: {STREAM_URL}")
    pool = None

    try:
        pool = await get_pool()
    except Exception as e:
        print(f"[LIQ] Không kết nối được DB, chỉ lưu CSV: {e}")

    attempt = 0
    while attempt < MAX_RECONNECT:
        try:
            async with websockets.connect(
                STREAM_URL,
                ping_interval=20,
                ping_timeout=30,
                close_timeout=10,
            ) as ws:
                print(f"[LIQ] ✅ Đã kết nối. Đang chờ liquidation...")
                attempt = 0
                total_saved = 0

                async for raw in ws:
                    msg = json.loads(raw)

                    # Bỏ qua gói handshake không có dữ liệu
                    if "e" not in msg:
                        continue

                    row = parse_liquidation(msg)
                    if row is None:
                        continue

                    await save_liquidation(pool, row)
                    total_saved += 1

                    usd = float(row["usd_value"])
                    direction = "SHORT ↑" if row["side"] == "BUY" else "LONG ↓"

                    if usd >= LOG_THRESHOLD_USD:
                        # Log lệnh lớn với emoji nổi bật
                        print(
                            f"[LIQ] 💥 {row['symbol']} | {direction} bị quét | "
                            f"${usd:,.0f} @ {row['price']} | "
                            f"{row['event_time'].strftime('%H:%M:%S')} | "
                            f"Tổng: {total_saved}"
                        )
                    else:
                        # Log nhỏ để xác nhận data đang chảy vào
                        print(
                            f"[LIQ] {row['symbol']} | {direction} | "
                            f"${usd:,.0f} | {row['event_time'].strftime('%H:%M:%S')}"
                        )

        except websockets.exceptions.ConnectionClosed as e:
            attempt += 1
            print(f"[LIQ] Mất kết nối ({e}). Reconnect {attempt}/{MAX_RECONNECT} sau {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)

        except Exception as e:
            attempt += 1
            print(f"[LIQ] Lỗi: {e}. Reconnect sau {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)

    print("[LIQ] ❌ Đã vượt quá số lần reconnect tối đa")


if __name__ == "__main__":
    init_csv_files()
    asyncio.run(run_liquidation_stream())