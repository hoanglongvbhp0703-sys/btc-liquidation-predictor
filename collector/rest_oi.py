"""
rest_oi.py — Poll Open Interest Binance Futures mỗi 30 giây
Endpoint: GET https://fapi.binance.com/fapi/v1/openInterest

Open Interest (OI) = tổng số lượng hợp đồng đang mở
- OI tăng → tiền mới vào thị trường → sắp có biến động
- OI giảm → lệnh đang đóng bớt → thị trường hạ nhiệt
"""

import asyncio
import aiohttp
from decimal import Decimal

from db import (
    get_pool, insert_oi, append_csv,
    ts_from_ms, now_utc, init_csv_files
)

# ─── Config ──────────────────────────────────────────────────
OI_ENDPOINT    = "https://fapi.binance.com/fapi/v1/openInterest"
PRICE_ENDPOINT = "https://fapi.binance.com/fapi/v1/ticker/price"
SYMBOL         = "BTCUSDT"
POLL_INTERVAL  = 15   # giây (trước 30s, tăng gấp đôi granularity)
RETRY_DELAY    = 10   # giây khi gặp lỗi


async def fetch_oi(session: aiohttp.ClientSession) -> dict | None:
    """Lấy Open Interest hiện tại."""
    try:
        async with session.get(
            OI_ENDPOINT,
            params={"symbol": SYMBOL},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                print(f"[OI] HTTP {resp.status}")
                return None
            return await resp.json()
    except Exception as e:
        print(f"[OI] Fetch OI error: {e}")
        return None


async def fetch_price(session: aiohttp.ClientSession) -> Decimal | None:
    """Lấy giá hiện tại để tính OI theo USD."""
    try:
        async with session.get(
            PRICE_ENDPOINT,
            params={"symbol": SYMBOL},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return Decimal(data["price"])
    except Exception as e:
        print(f"[OI] Fetch price error: {e}")
        return None


def parse_oi(oi_data: dict, price: Decimal) -> dict:
    """
    Kết hợp OI + price → row chuẩn.

    Response từ Binance:
    {
      "openInterest": "10659.509",   ← số lượng BTC
      "symbol": "BTCUSDT",
      "time": 1589437530011
    }
    """
    oi_btc = Decimal(oi_data["openInterest"])
    oi_usd = oi_btc * price if price else Decimal(0)

    return {
        "timestamp": ts_from_ms(oi_data["time"]),
        "oi_btc":    oi_btc,
        "oi_usd":    oi_usd,
    }


async def save_oi(pool, row: dict):
    """Lưu vào CSV và TimescaleDB."""
    append_csv("oi", [
        row["timestamp"].isoformat(),
        str(row["oi_btc"]),
        str(row["oi_usd"]),
    ])

    if pool:
        try:
            await insert_oi(pool, row)
        except Exception as e:
            print(f"[OI] DB error: {e}")


async def run_oi_poller():
    """Poll OI mỗi POLL_INTERVAL giây. Chạy mãi mãi với error handling."""
    print(f"[OI] Bắt đầu poll mỗi {POLL_INTERVAL}s: {OI_ENDPOINT}")
    pool = None

    try:
        pool = await get_pool()
    except Exception as e:
        print(f"[OI] Không kết nối được DB, chỉ lưu CSV: {e}")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                oi_data, price = await asyncio.gather(
                    fetch_oi(session),
                    fetch_price(session),
                )

                if oi_data is None:
                    print(f"[OI] Không lấy được data, thử lại sau {RETRY_DELAY}s")
                    await asyncio.sleep(RETRY_DELAY)
                    continue

                row = parse_oi(oi_data, price or Decimal(0))
                await save_oi(pool, row)

                print(
                    f"[OI] {row['timestamp'].strftime('%H:%M:%S')} | "
                    f"OI = {float(row['oi_btc']):,.2f} BTC "
                    f"(${float(row['oi_usd']) / 1e9:.2f}B)"
                )

                await asyncio.sleep(POLL_INTERVAL)

            except asyncio.CancelledError:
                print("[OI] Đã dừng poller")
                break
            except Exception as e:
                print(f"[OI] Lỗi không xác định: {e}. Thử lại sau {RETRY_DELAY}s")
                await asyncio.sleep(RETRY_DELAY)


if __name__ == "__main__":
    init_csv_files()
    asyncio.run(run_oi_poller())