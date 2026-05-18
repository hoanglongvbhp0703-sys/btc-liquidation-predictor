"""
rest_basis.py — Poll futures-spot basis từ premiumIndex mỗi 30s

Basis = (markPrice - indexPrice) / indexPrice × 100  (%)

  > 0: futures đang premium so với spot → longs nhiều, shorts at risk
  < 0: futures đang discount so với spot → shorts nhiều, longs at risk

Khi basis đột ngột bật từ âm sang dương → dấu hiệu short squeeze.

Output: data/basis.csv
  timestamp, mark_price, index_price, basis_pct
"""

import asyncio
import aiohttp

from db import append_csv, now_utc, init_csv_files

ENDPOINT     = "https://fapi.binance.com/fapi/v1/premiumIndex"
SYMBOL       = "BTCUSDT"
POLL_INTERVAL = 15   # giây (trước 30s, tăng gấp đôi granularity)
RETRY_DELAY   = 10


async def run_basis_poller():
    print(f"[BASIS] Poll basis mỗi {POLL_INTERVAL}s: {ENDPOINT}")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(
                    ENDPOINT,
                    params={"symbol": SYMBOL},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        print(f"[BASIS] HTTP {resp.status}")
                        await asyncio.sleep(RETRY_DELAY)
                        continue

                    data       = await resp.json()
                    mark_price = float(data["markPrice"])
                    idx_price  = float(data["indexPrice"])
                    basis_pct  = round((mark_price - idx_price) / idx_price * 100, 6)

                    row = [
                        now_utc().isoformat(),
                        str(mark_price),
                        str(idx_price),
                        str(basis_pct),
                    ]
                    append_csv("basis", row)

                    sign = "+" if basis_pct >= 0 else ""
                    print(f"[BASIS] {sign}{basis_pct:.4f}%  mark={mark_price:.2f}  idx={idx_price:.2f}")

            except asyncio.CancelledError:
                print("[BASIS] Đã dừng.")
                break
            except Exception as e:
                print(f"[BASIS] Lỗi: {e}. Thử lại sau {RETRY_DELAY}s")
                await asyncio.sleep(RETRY_DELAY)
                continue

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    init_csv_files()
    try:
        asyncio.run(run_basis_poller())
    except KeyboardInterrupt:
        print("\n[BASIS] Đã dừng.")
