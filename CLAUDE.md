# BTC Liquidation Predictor — Project Context

## Mục đích

Real-time ML system dự đoán BTC có chạm vùng liquidation trên/dưới trong N phút tới không.
- Input: 6 luồng dữ liệu Binance Futures (WebSocket + REST)
- Output: Xác suất LONG/SHORT chạm liq zone, signal paper trading, dashboard web real-time

---

## Kiến trúc 6 tầng (tất cả đã hoàn tất)

```
Binance Futures
     │
     ▼
Tầng 1 — collector/          ← 6 async streams → data/raw/*.csv
     │
     ▼
Tầng 2 — feature_engine/     ← 39 features mỗi 5 phút → data/processed/features_5m.csv
     │
     ▼
Tầng 3 — feature_engine/label_builder.py  ← điền label sau 30 phút
     │
     ▼
Tầng 4 — ml/train.py + predict.py        ← LightGBM, 12 models (6 horizons × LONG+SHORT)
     │
     ▼
Tầng 5 — signal/run.py                   ← paper trading, Telegram alert
     │
     ▼
Tầng 6 — server/ (Django + Channels)     ← dashboard http://localhost:8000
```

Các tầng giao tiếp qua **CSV files** — không dùng message broker.

---

## Trạng thái hiện tại

| Tầng | Module | Status |
|---|---|---|
| 1 | collector/ | ✅ hoàn tất |
| 2 | feature_engine/ | ✅ hoàn tất |
| 3 | label_builder.py | ✅ hoàn tất |
| 4 | ml/train.py, predict.py | ✅ hoàn tất |
| 5 | signal/ | ✅ hoàn tất |
| 6 | server/ (Django) | ✅ hoàn tất |

**Giai đoạn hiện tại:** Đang tích lũy labeled data từ Binance thật.
Mục tiêu: ~2,000 labeled rows → retrain → monitor paper trading 2 tuần → live.

---

## File structure quan trọng

```
collector/
  main.py              # asyncio entry — chạy 6 coroutine song song
  ws_kline.py          # kline_1m snapshot 1s → klines_1s.csv
  ws_liquidation.py    # forceOrder@arr → liquidations.csv
  ws_orderbook.py      # depth20@500ms → orderbook.csv
  ws_aggtrade.py       # aggTrade + CVD batch → aggtrades.csv
  rest_oi.py           # open interest mỗi 30s → open_interest.csv
  rest_funding.py      # funding rate mỗi 1h → funding_rate.csv
  db.py                # CSV append helper

feature_engine/
  run.py               # scheduler 5 phút
  build_features.py    # merge tất cả feat_*.py → 1 row features_5m.csv
  label_builder.py     # TẦNG 3: điền label_Xm và label_short_Xm
  load_data.py         # đọc CSV raw
  feat_price.py / feat_liquidation.py / feat_orderbook.py
  feat_aggtrade.py / feat_oi.py / feat_funding.py

ml/
  train.py             # train 12 LightGBM models (LONG+SHORT × 6 horizons)
  predict.py           # load_model(), predict_proba(), predict_signal(), predict_curve_*()
  artifacts/           # lgb_model_long_Xm.pkl, lgb_model_short_Xm.pkl, meta.json (gitignored)

signal/
  run.py               # inference loop mỗi 5 phút
  paper_log.py         # ghi + check outcome (WIN/LOSS/EXPIRED)
  notifier.py          # Telegram alert (opt-in)

server/
  btc_dashboard/settings.py   # ROOT_DIR, DATA_DIR, CHANNEL_LAYERS, ASGI_APPLICATION
  btc_dashboard/asgi.py       # ProtocolTypeRouter: http → Django, ws → TickConsumer
  dashboard/broadcaster.py    # background thread: đọc data 1s → push WS group "tick"
  dashboard/consumers.py      # TickConsumer (AsyncWebsocketConsumer)
  dashboard/data_reader.py    # đọc CSV → dict (fast tail + full load)
  dashboard/views.py          # REST: /api/klines/ /api/signal/ /api/trades/ /api/liq/
  static/js/chart.js          # Lightweight Charts (nến + liq zones)
  static/js/signal.js         # prob bar + countdown + curve chart
  templates/dashboard/index.html

scripts/
  generate_fake_data.py  # sinh synthetic data + train mock model (dev/demo)

docker/docker-compose.yml  # 4 services: collector, feature_engine, signal, dashboard
```

---

## Data files (data/ — gitignored, tạo lúc runtime)

```
data/raw/
  klines_1s.csv        # open_time, open, high, low, close, volume, taker_buy_vol, num_trades
  liquidations.csv     # event_time, symbol, side, price, qty, usd_value
  orderbook.csv        # timestamp, bid1..bid5, ask1..ask5, mid_price, spread, imbalance
  aggtrades.csv        # timestamp, agg_id, price, qty, usd_value, is_buyer_maker, cvd_delta
  open_interest.csv    # timestamp, oi_btc, oi_usd
  funding_rate.csv     # timestamp, funding_rate, next_funding_time

data/processed/
  features_5m.csv      # 39 features + label_5m..label_30m + label_short_5m..label_short_30m
  paper_trades.csv     # opened_at, signal, prob, entry, tp, sl, rr, closed_at, outcome, pnl_pct
```

---

## ML Model — LightGBM

**Tại sao LightGBM:** benchmark 8 thuật toán (notebook model_comparison.ipynb) → LightGBM tốt nhất AUC + Brier score.

**12 models:** LONG × {5,10,15,20,25,30}m + SHORT × {5,10,15,20,25,30}m

**39 features:**
- Giá: price_change_5m/1m, volatility_5m, volume_5m, taker_buy_ratio
- Liquidation: liq_long/short_usd_5m, liq_ratio_5m, dist_to_upper/lower
- Order book: imbalance_now/avg_1m/trend, spread_now, bid_vol_now, ask_vol_now, wall_ratio
- CVD+Whale: cvd_delta_5m/1m, whale_buy/sell_count/net/usd_5m, whale_dominance
- OI: delta_oi_5m/30m/1h, oi_acceleration
- Funding: funding_rate, funding_rate_abs, funding_bias, funding_long/short_heavy, funding_rate_change, funding_trend_3h, secs_to_next_funding, funding_urgency

**Label logic:**
- `label_Xm = 1` nếu `max(high[T → T+Xm]) >= liq_zone_upper`
- `label_short_Xm = 1` nếu `min(low[T → T+Xm]) <= liq_zone_lower`
- `label = label_30m` (alias backward compat)
- Mã đặc biệt: `-1` = zone null, `-2` = không đủ kline data

**Signal condition:** prob >= 0.70 AND R:R >= 1.5

---

## Dashboard (Tầng 6)

- Stack: Django 4.2 + Channels 4 + Daphne (ASGI)
- broadcaster.py push tick mỗi 1s qua WebSocket `/ws/tick/` tới group `"tick"`
- Tick payload: price, liq_upper/lower, prob_long, prob_short, prob_curve_long/short (dict {5→p,...,30→p}), signal_long, signal_short
- FE: Lightweight Charts (nến), Chart.js (CVD bar), prob bar + countdown, paper trades table

---

## Lệnh chạy

```bash
# Development (synthetic data)
make fake-data      # generate_fake_data.py → sinh CSV + train mock model
make server         # cd server && python manage.py runserver 0.0.0.0:8000

# Production (từng service riêng)
make collector      # python collector/main.py
make features       # python feature_engine/run.py
make signal         # python signal/run.py
make server         # cd server && daphne -b 0.0.0.0 -p 8000 btc_dashboard.asgi:application

# Docker (4 services)
docker compose -f docker/docker-compose.yml up -d

# Train model (cần ≥200 rows labeled, khuyến nghị 2000+)
make train          # python ml/train.py

# Tests
make test           # unit + integration
```

---

## Env vars (.env)

| Var | Bắt buộc | Mặc định |
|---|---|---|
| DJANGO_SECRET_KEY | Yes | — |
| SIGNAL_THRESHOLD | No | 0.70 |
| TELEGRAM_BOT_TOKEN | No | — |
| TELEGRAM_CHAT_ID | No | — |
| BINANCE_API_KEY/SECRET | No | chỉ cần cho private endpoints |

---

## Roadmap còn lại

- [ ] Đạt ~2,000 labeled rows từ Binance thật
- [ ] Retrain LightGBM trên real data (target AUC ≥ 0.75 live)
- [ ] Xác minh thống kê thủ công: khi dist_to_upper < 1.5% + imbalance > 0.6 + cvd > 0, win rate thực tế là bao nhiêu?
- [ ] Optuna hyperparameter tuning
- [ ] Walk-forward backtesting module
- [ ] Live PnL thay paper trading
- [ ] Multi-symbol (ETH, SOL)

---

## Lưu ý kỹ thuật quan trọng

- `klines_1s.csv` dùng `now_utc()` cho timestamp (snapshot lúc ghi), không phải `open_time` của nến Binance
- `ws_orderbook.py` phải dùng `/stream?streams=btcusdt@depth20@500ms` (không phải `/market/ws/`) vì Binance wrap data trong `{"stream": "...", "data": {...}}`
- broadcaster.py thêm noise sin vào CVD để trông "live" khi không có collector chạy
- Signal LONG: ưu tiên paper trade đang mở từ `signal/run.py`; Signal SHORT: tính real-time từ broadcaster
- Model artifacts: `lgb_model_long_Xm.pkl` + `imputer_long_Xm.pkl` (6 horizons); `lgb_model_long.pkl` = alias 30m (backward compat)
