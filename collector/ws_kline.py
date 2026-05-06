import json
import asyncio
import websockets
from decimal import Decimal

from db import (
    append_csv, ts_from_ms, now_utc,
    init_csv_files, get_pool,
    insert_kline
)

# ─── Cấu hình ──────────────────────────────────────────────────
# Binance Futures không có interval 1s → dùng 1m, update mỗi 250ms
# Mỗi giây chỉ ghi 1 dòng (snapshot tại giây đó)
STREAM_URL      = "wss://fstream.binance.com/market/ws/btcusdt@kline_1m"
RECONNECT_DELAY = 5
MAX_RECONNECT   = 999
WRITE_INTERVAL  = 1.0  # giây


async def run_kline_stream():
    """
    Nhận update 250ms từ Binance nhưng chỉ ghi CSV mỗi 1 giây.
    Buffer giữ gói tin mới nhất, writer task flush mỗi giây 1 lần.
    """
    print(f"[KLINE] Kết nối tới: {STREAM_URL}")
    pool = None

    try:
        pool = await get_pool()
    except Exception:
        pass

    attempt = 0
    while attempt < MAX_RECONNECT:
        try:
            async with websockets.connect(
                STREAM_URL,
                ping_interval=20,
                ping_timeout=30,
                close_timeout=10
            ) as ws:
                print(f"[KLINE] ✅ Đã kết nối. Ghi CSV mỗi {WRITE_INTERVAL}s...")
                attempt = 0

                latest: dict | None = None

                async def writer_task():
                    nonlocal latest
                    while True:
                        await asyncio.sleep(WRITE_INTERVAL)
                        if latest is None:
                            continue

                        k = latest
                        latest = None

                        row_data = [
                            now_utc().isoformat(),
                            str(k["o"]),
                            str(k["h"]),
                            str(k["l"]),
                            str(k["c"]),
                            str(k["v"]),
                            str(k["V"]),
                            str(k["n"])
                        ]

                        append_csv("klines", row_data)
                        print(f"[KLINE] {row_data[0]} | Close: {row_data[4]}")

                        if pool:
                            await insert_kline(pool, {
                                "open_time":     ts_from_ms(k["t"]),
                                "open":          Decimal(k["o"]),
                                "high":          Decimal(k["h"]),
                                "low":           Decimal(k["l"]),
                                "close":         Decimal(k["c"]),
                                "volume":        Decimal(k["v"]),
                                "taker_buy_vol": Decimal(k["V"]),
                                "num_trades":    int(k["n"])
                            })

                writer = asyncio.create_task(writer_task())

                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        if "k" not in msg:
                            continue
                        latest = msg["k"]
                finally:
                    writer.cancel()
                    await asyncio.gather(writer, return_exceptions=True)

        except (websockets.exceptions.ConnectionClosed, Exception) as e:
            attempt += 1
            print(f"[KLINE] ⚠️  Mất kết nối: {e}. Thử lại {attempt}/{MAX_RECONNECT} sau {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)

    print("[KLINE] ❌ Vượt quá số lần reconnect tối đa")


if __name__ == "__main__":
    init_csv_files()
    try:
        asyncio.run(run_kline_stream())
    except KeyboardInterrupt:
        print("\n[KLINE] Đã dừng bởi người dùng.")