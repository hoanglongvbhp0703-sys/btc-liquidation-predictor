"""
rest_premium_index.py — Poll /fapi/v1/premiumIndex mỗi 15 giây

Thay thế rest_funding.py (5m) + rest_basis.py (15s) bằng 1 collector duy nhất.
Cùng 1 HTTP call → đủ cả funding + basis, cùng timestamp, không lệch nhau.

Output: premium_index.csv
  timestamp, funding_rate, next_funding_time, mark_price, index_price, basis_pct
"""

import asyncio
import sys
import aiohttp
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SYMBOL

from db import append_csv, now_utc, ts_from_ms, init_csv_files

ENDPOINT      = "https://fapi.binance.com/fapi/v1/premiumIndex"
POLL_INTERVAL = 15   # giây
RETRY_DELAY   = 10


async def run_premium_index_poller():
    print(f"[PREM] Poll premiumIndex mỗi {POLL_INTERVAL}s ({SYMBOL}): {ENDPOINT}")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(
                    ENDPOINT,
                    params={"symbol": SYMBOL},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        print(f"[PREM] HTTP {resp.status}")
                        await asyncio.sleep(RETRY_DELAY)
                        continue

                    data        = await resp.json()
                    mark_price  = float(data["markPrice"])
                    index_price = float(data["indexPrice"])
                    funding_rate = data["lastFundingRate"]
                    next_ts     = ts_from_ms(int(data["nextFundingTime"])).isoformat()
                    basis_pct   = round((mark_price - index_price) / index_price * 100, 6)

                    row = [
                        now_utc().isoformat(),
                        funding_rate,
                        next_ts,
                        str(mark_price),
                        str(index_price),
                        str(basis_pct),
                    ]
                    append_csv("premium_index", row)

                    sign = "+" if basis_pct >= 0 else ""
                    fr   = float(funding_rate)
                    print(
                        f"[PREM] basis={sign}{basis_pct:.4f}% | "
                        f"funding={fr * 100:.4f}% | "
                        f"mark={mark_price:.2f}"
                    )

            except asyncio.CancelledError:
                print("[PREM] Đã dừng.")
                break
            except Exception as e:
                print(f"[PREM] Lỗi: {e}. Thử lại sau {RETRY_DELAY}s")
                await asyncio.sleep(RETRY_DELAY)
                continue

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    init_csv_files()
    try:
        asyncio.run(run_premium_index_poller())
    except KeyboardInterrupt:
        print("\n[PREM] Đã dừng.")
