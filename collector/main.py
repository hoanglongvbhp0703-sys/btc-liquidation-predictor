"""
main.py — Entry point: chạy 8 collector đồng thời

Cách chạy:
    python main.py

Cấu trúc thư mục output:
    data/
    ├── klines_1s.csv       ← nến 1m futures (snapshot mỗi 1s)
    ├── liquidations.csv    ← liquidation events real-time
    ├── open_interest.csv   ← OI mỗi 30s
    ├── funding_rate.csv    ← funding rate mỗi 1h
    ├── orderbook.csv       ← top 5 bid/ask + imbalance mỗi 1s
    ├── aggtrades.csv       ← Futures CVD + whale trades real-time
    ├── spot_aggtrades.csv  ← Spot CVD (divergence signal) mỗi 1s batch
    └── basis.csv           ← Futures-spot basis mỗi 30s
"""

import asyncio
import signal
import sys
from pathlib import Path

from db import init_csv_files, init_db, close_pool
from ws_kline import run_kline_stream
from ws_liquidation import run_liquidation_stream
from ws_orderbook import run_orderbook_stream
from ws_aggtrade import run_aggtrade_stream
from ws_spot_aggtrade import run_spot_aggtrade_stream
from rest_oi import run_oi_poller
from rest_funding import run_funding_poller
from rest_basis import run_basis_poller


def handle_shutdown(loop, tasks):
    """Dừng tất cả task khi nhận Ctrl+C."""
    print("\n[MAIN] Nhận tín hiệu dừng, đang shutdown...")
    for task in tasks:
        task.cancel()


async def health_monitor():
    """In trạng thái hệ thống mỗi 5 phút."""
    data_dir = Path(__file__).parent.parent / "data"
    files = {
        "klines_1s.csv":      "Nến 1s",
        "liquidations.csv":   "Liquidation",
        "open_interest.csv":  "Open Interest",
        "funding_rate.csv":   "Funding Rate",
        "orderbook.csv":      "Order Book",
        "aggtrades.csv":      "Futures CVD",
        "spot_aggtrades.csv": "Spot CVD",
        "basis.csv":          "Basis",
    }

    while True:
        await asyncio.sleep(300)

        print("\n" + "=" * 55)
        print("[HEALTH] Trạng thái collector:")
        for filename, label in files.items():
            filepath = data_dir / filename
            if filepath.exists():
                size_kb = filepath.stat().st_size / 1024
                with open(filepath) as f:
                    lines = sum(1 for _ in f) - 1
                print(f"  ✅ {label:<18}: {lines:>8,} dòng ({size_kb:.1f} KB)")
            else:
                print(f"  ❌ {label:<18}: chưa có file")
        print("=" * 55 + "\n")


async def main():
    print("""
╔══════════════════════════════════════════════════╗
║   BTC Futures Collector — Tầng 1                 ║
║   Binance USDS-M  |  8 streams                   ║
║                                                  ║
║   kline · liquidation · OI · funding             ║
║   orderbook · futures CVD · spot CVD · basis                       ║
╚══════════════════════════════════════════════════╝
    """)

    print("[MAIN] Khởi tạo file CSV...")
    init_csv_files()

    print("[MAIN] Thử kết nối TimescaleDB...")
    try:
        await init_db()
    except Exception as e:
        print(f"[MAIN] ⚠️  Không kết nối được DB: {e}")
        print("[MAIN] Tiếp tục chỉ với CSV...")

    print("[MAIN] Khởi động 8 collector...\n")

    tasks = [
        asyncio.create_task(run_kline_stream(),           name="kline"),
        asyncio.create_task(run_liquidation_stream(),     name="liquidation"),
        asyncio.create_task(run_orderbook_stream(),       name="orderbook"),
        asyncio.create_task(run_aggtrade_stream(),        name="aggtrade"),
        asyncio.create_task(run_spot_aggtrade_stream(),   name="spot_aggtrade"),
        asyncio.create_task(run_oi_poller(),              name="oi"),
        asyncio.create_task(run_funding_poller(),         name="funding"),
        asyncio.create_task(run_basis_poller(),           name="basis"),
        asyncio.create_task(health_monitor(),             name="health"),
    ]

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown, loop, tasks)

    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_EXCEPTION
        )
        for task in done:
            if task.exception():
                print(f"[MAIN] ❌ Task '{task.get_name()}' lỗi: {task.exception()}")

    except asyncio.CancelledError:
        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_pool()
        print("[MAIN] Đã dừng tất cả collector")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[MAIN] Đã dừng bởi người dùng")
        sys.exit(0)