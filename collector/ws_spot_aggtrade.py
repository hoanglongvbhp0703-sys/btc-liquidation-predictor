"""
ws_spot_aggtrade.py — Spot CVD WebSocket (Binance Spot aggTrade)

Mục đích: Thu thập CVD thị trường SPOT để phát hiện divergence với futures.
  - Futures CVD âm nhưng Spot CVD dương → ai đó mua spot mạnh trong khi
    futures đang bị bán → tín hiệu short squeeze tiềm năng (LONG cascade)

Stream: wss://stream.binance.com:9443/ws/btcusdt@aggTrade
Output: data/spot_aggtrades.csv (cùng format với aggtrades.csv)

Ghi: batch mỗi 1s (không ghi lệnh đơn lẻ — spot volume quá lớn)
"""

import json
import asyncio
from decimal import Decimal

import websockets

from db import append_csv, now_utc, init_csv_files

STREAM_URL      = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
RECONNECT_DELAY = 5
MAX_RECONNECT   = 999
WRITE_INTERVAL  = 1.0


async def run_spot_aggtrade_stream():
    print(f"[SPOT-AGG] Kết nối tới: {STREAM_URL}")
    attempt = 0

    while attempt < MAX_RECONNECT:
        try:
            async with websockets.connect(
                STREAM_URL,
                ping_interval=20,
                ping_timeout=30,
                close_timeout=10,
            ) as ws:
                print("[SPOT-AGG] ✅ Đã kết nối spot aggTrade stream")
                attempt = 0
                small_buffer: list = []

                async def writer_task():
                    nonlocal small_buffer
                    while True:
                        await asyncio.sleep(WRITE_INTERVAL)
                        if not small_buffer:
                            continue

                        batch       = small_buffer
                        small_buffer = []

                        buy_vol  = sum(t[1] for t in batch if not t[2])
                        sell_vol = sum(t[1] for t in batch if t[2])
                        cvd_delta = buy_vol - sell_vol
                        usd_value = sum(t[0] * t[1] for t in batch)
                        total_vol = buy_vol + sell_vol
                        last_price = batch[-1][0]

                        row = [
                            now_utc().isoformat(),
                            "BATCH",
                            str(last_price),
                            str(total_vol),
                            str(usd_value),
                            "False",   # mixed batch — placeholder
                            str(cvd_delta),
                        ]
                        append_csv("spot_aggtrade", row)

                writer = asyncio.create_task(writer_task())
                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("e") != "aggTrade":
                            continue

                        price          = Decimal(msg["p"])
                        qty            = Decimal(msg["q"])
                        is_buyer_maker = msg["m"]
                        small_buffer.append((price, qty, is_buyer_maker))
                finally:
                    writer.cancel()
                    await asyncio.gather(writer, return_exceptions=True)

        except (websockets.exceptions.ConnectionClosed, Exception) as e:
            attempt += 1
            print(f"[SPOT-AGG] ⚠️  Mất kết nối: {e}. Thử lại {attempt}/{MAX_RECONNECT} sau {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)

    print("[SPOT-AGG] ❌ Vượt quá số lần reconnect tối đa")


if __name__ == "__main__":
    init_csv_files()
    try:
        asyncio.run(run_spot_aggtrade_stream())
    except KeyboardInterrupt:
        print("\n[SPOT-AGG] Đã dừng.")
