"""
ws_aggtrade.py — WebSocket AggTrade + CVD Binance Futures
Stream: wss://fstream.binance.com/market/ws/btcusdt@aggTrade

AggTrade là gì?
  Binance gom tất cả lệnh khớp cùng giá, cùng hướng trong cùng 1ms
  thành 1 aggTrade. Mỗi aggTrade = 1 "cú đánh" thực sự vào thị trường.

CVD (Cumulative Volume Delta) là gì?
  CVD = tổng tích lũy của (volume mua chủ động - volume bán chủ động)
  - CVD tăng liên tục → phe mua đang tấn công → giá có xu hướng lên
  - CVD giảm liên tục → phe bán đang tấn công → giá có xu hướng xuống
  - CVD diverge với giá → tín hiệu đảo chiều sắp xảy ra

  Ví dụ từ log thực tế của bạn lúc 03:13:
  - Giá BTC giảm từ 80360 → 80297
  - Nếu CVD vẫn tăng trong lúc giá giảm → divergence bullish
    → có thể là cá mập đang accumulate trước khi đẩy lên

Chiến lược ghi:
  - aggTrade volume lớn (>$50K): ghi NGAY LẬP TỨC
  - aggTrade nhỏ hơn: buffer 1 giây, ghi 1 batch
  → Giữ được mọi "cú đánh cá mập" mà không bị ngập data

Tại sao không ghi tất cả real-time?
  BTCUSDT có ~5000-10000 aggTrades/phút → ~7M dòng/ngày → quá lớn
  Với chiến lược buffer 1s: ~60-86400 dòng/ngày → manageable
"""

import json
import asyncio
import websockets
from decimal import Decimal

from db import (
    append_csv, ts_from_ms,
    init_csv_files, get_pool,
    insert_aggtrade
)

# ─── Cấu hình ──────────────────────────────────────────────────
STREAM_URL      = "wss://fstream.binance.com/market/ws/btcusdt@aggTrade"
RECONNECT_DELAY = 5
MAX_RECONNECT   = 999
WRITE_INTERVAL  = 1.0      # giây — ghi batch mỗi 1s
LARGE_TRADE_USD = 50_000   # $50K → ghi ngay lập tức, không chờ buffer


async def run_aggtrade_stream():
    """
    Stream aggTrade với 2 chế độ ghi:
    1. Lệnh lớn (>$50K): ghi ngay lập tức
    2. Lệnh nhỏ: gom 1 giây rồi ghi tổng hợp (OHLCV style)
       - open/close/high/low price trong giây
       - tổng buy vol, tổng sell vol → CVD delta của giây đó
    """
    print(f"[AGG] Kết nối tới: {STREAM_URL}")
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
                print(f"[AGG] ✅ Đã kết nối. Large trade ≥ ${LARGE_TRADE_USD:,} ghi ngay...")
                attempt = 0

                # Buffer gom lệnh nhỏ trong 1 giây
                # Mỗi phần tử: (price, qty, is_buyer_maker)
                small_buffer: list = []
                # CVD tích lũy toàn session (reset khi reconnect)
                cumulative_cvd = Decimal("0")

                async def writer_task():
                    nonlocal small_buffer, cumulative_cvd
                    while True:
                        await asyncio.sleep(WRITE_INTERVAL)
                        if not small_buffer:
                            continue

                        batch = small_buffer
                        small_buffer = []

                        # Tổng hợp batch thành 1 dòng OHLCV-style
                        prices    = [t[0] for t in batch]
                        buy_vol   = sum(t[1] for t in batch if not t[2])   # is_buyer_maker=False → mua CĐ
                        sell_vol  = sum(t[1] for t in batch if t[2])       # is_buyer_maker=True  → bán CĐ
                        total_vol = buy_vol + sell_vol
                        cvd_delta = buy_vol - sell_vol

                        usd_value = sum(t[0] * t[1] for t in batch)

                        from db import now_utc
                        row = [
                            now_utc().isoformat(),
                            "BATCH",                    # agg_id = BATCH để phân biệt
                            str(prices[-1]),            # close price của giây
                            str(total_vol),             # tổng volume
                            str(usd_value),             # tổng USD
                            str(len([t for t in batch if not t[2]])),  # số lệnh mua CĐ
                            str(cvd_delta),             # CVD delta giây này
                        ]
                        append_csv("aggtrade", row)

                        # Log CVD để theo dõi
                        direction = "🟢" if cvd_delta > 0 else "🔴"
                        print(
                            f"[AGG] 1s batch | "
                            f"Buy: {float(buy_vol):.2f} | Sell: {float(sell_vol):.2f} | "
                            f"CVD Δ: {direction}{float(cvd_delta):.2f} | "
                            f"CVD cum: {float(cumulative_cvd):.2f}"
                        )

                writer = asyncio.create_task(writer_task())

                try:
                    async for raw in ws:
                        msg = json.loads(raw)

                        # Bỏ qua gói không phải aggTrade
                        if msg.get("e") != "aggTrade":
                            continue

                        price          = Decimal(msg["p"])
                        qty            = Decimal(msg["q"])
                        usd_value      = price * qty
                        is_buyer_maker = msg["m"]  # True = seller là taker (bán chủ động)
                        agg_id         = msg["a"]
                        ts             = ts_from_ms(msg["T"]).isoformat()

                        # CVD delta cho lệnh này
                        cvd_delta = -qty if is_buyer_maker else qty
                        cumulative_cvd += cvd_delta

                        if float(usd_value) >= LARGE_TRADE_USD:
                            # ─── Lệnh LỚN: ghi ngay lập tức ───────────────
                            row = [
                                ts,
                                str(agg_id),
                                str(price),
                                str(qty),
                                str(usd_value),
                                str(is_buyer_maker),
                                str(cvd_delta),
                            ]
                            append_csv("aggtrade", row)

                            side = "🔴 SELL" if is_buyer_maker else "🟢 BUY "
                            print(
                                f"[AGG] 🐋 {side} ${float(usd_value):,.0f} "
                                f"@ {price} | CVD cum: {float(cumulative_cvd):.2f}"
                            )

                            if pool:
                                await insert_aggtrade(pool, row)
                        else:
                            # ─── Lệnh NHỎ: đưa vào buffer ──────────────────
                            small_buffer.append((price, qty, is_buyer_maker))

                finally:
                    writer.cancel()
                    await asyncio.gather(writer, return_exceptions=True)

        except (websockets.exceptions.ConnectionClosed, Exception) as e:
            attempt += 1
            print(f"[AGG] ⚠️  Mất kết nối: {e}. Thử lại {attempt}/{MAX_RECONNECT} sau {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)

    print("[AGG] ❌ Vượt quá số lần reconnect tối đa")


if __name__ == "__main__":
    init_csv_files()
    try:
        asyncio.run(run_aggtrade_stream())
    except KeyboardInterrupt:
        print("\n[AGG] Đã dừng bởi người dùng.")