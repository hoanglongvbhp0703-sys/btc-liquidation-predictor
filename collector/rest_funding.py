"""
rest_funding.py — Poll Funding Rate Binance Futures mỗi 1 giờ
Endpoint: GET https://fapi.binance.com/fapi/v1/premiumIndex

Funding Rate là phí định kỳ giữa LONG và SHORT (mỗi 8 tiếng):
  > +0.01% → thị trường đang nghiêng LONG quá nhiều
             SHORT nhận tiền từ LONG
  < -0.01% → thị trường đang nghiêng SHORT quá nhiều
             LONG nhận tiền từ SHORT
"""

import asyncio
import aiohttp
from decimal import Decimal

from db import (
    get_pool, insert_funding, append_csv,
    ts_from_ms, now_utc, init_csv_files
)

# ─── Config ──────────────────────────────────────────────────
FUNDING_ENDPOINT = "https://fapi.binance.com/fapi/v1/premiumIndex"
SYMBOL           = "BTCUSDT"
POLL_INTERVAL    = 3600  # 1 giờ
RETRY_DELAY      = 60    # 1 phút khi gặp lỗi


async def fetch_funding(session: aiohttp.ClientSession) -> dict | None:
    """
    Lấy funding rate hiện tại từ premiumIndex.
    Dùng premiumIndex vì trả về funding rate HIỆN TẠI (chưa settle),
    khác với fundingRate chỉ trả về lịch sử đã settle.
    """
    try:
        async with session.get(
            FUNDING_ENDPOINT,
            params={"symbol": SYMBOL},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                print(f"[FUNDING] HTTP {resp.status}")
                return None
            return await resp.json()
    except Exception as e:
        print(f"[FUNDING] Fetch error: {e}")
        return None


def parse_funding(data: dict) -> dict:
    """
    Parse response từ premiumIndex.

    Response:
    {
      "symbol": "BTCUSDT",
      "markPrice": "11793.63104562",
      "indexPrice": "11781.80495970",
      "lastFundingRate": "0.00038246",   ← funding rate hiện tại
      "nextFundingTime": 1597392000000,  ← lần settle tiếp theo (ms)
      "time": 1597370495002
    }
    """
    return {
        "timestamp":         ts_from_ms(data["time"]),
        "funding_rate":      Decimal(data["lastFundingRate"]),
        "next_funding_time": ts_from_ms(data["nextFundingTime"]),
    }


async def save_funding(pool, row: dict):
    """Lưu vào CSV và TimescaleDB."""
    append_csv("funding", [
        row["timestamp"].isoformat(),
        str(row["funding_rate"]),
        row["next_funding_time"].isoformat(),
    ])

    if pool:
        try:
            await insert_funding(pool, row)
        except Exception as e:
            print(f"[FUNDING] DB error: {e}")


async def run_funding_poller():
    """
    Poll Funding Rate mỗi POLL_INTERVAL giây.
    Fetch ngay lập tức khi start, sau đó chờ mỗi tiếng.
    """
    print(f"[FUNDING] Bắt đầu poll mỗi {POLL_INTERVAL // 3600}h: {FUNDING_ENDPOINT}")
    pool = None

    try:
        pool = await get_pool()
    except Exception as e:
        print(f"[FUNDING] Không kết nối được DB, chỉ lưu CSV: {e}")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                data = await fetch_funding(session)

                if data is None:
                    print(f"[FUNDING] Không lấy được data, thử lại sau {RETRY_DELAY}s")
                    await asyncio.sleep(RETRY_DELAY)
                    continue

                row = parse_funding(data)
                await save_funding(pool, row)

                fr = float(row["funding_rate"])
                if fr > 0.0001:
                    signal = "⚠️  LONG quá nhiều — rủi ro bị quét lên"
                elif fr < -0.0001:
                    signal = "⚠️  SHORT quá nhiều — rủi ro bị quét xuống"
                else:
                    signal = "✅ Trung tính"

                print(
                    f"[FUNDING] {row['timestamp'].strftime('%H:%M:%S')} | "
                    f"Rate = {fr * 100:.4f}% | "
                    f"Next = {row['next_funding_time'].strftime('%H:%M')} | "
                    f"{signal}"
                )

                await asyncio.sleep(POLL_INTERVAL)

            except asyncio.CancelledError:
                print("[FUNDING] Đã dừng poller")
                break
            except Exception as e:
                print(f"[FUNDING] Lỗi không xác định: {e}. Thử lại sau {RETRY_DELAY}s")
                await asyncio.sleep(RETRY_DELAY)


if __name__ == "__main__":
    init_csv_files()
    asyncio.run(run_funding_poller())