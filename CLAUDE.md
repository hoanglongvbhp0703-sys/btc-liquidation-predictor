# BTC Cascade Liquidation Predictor — Project Context

## Mục đích

Real-time ML system dự đoán BTC có xảy ra cascade liquidation trong 1/2/3 phút tới không.
- Input: 8 luồng dữ liệu Binance Futures (WebSocket + REST)
- Output: Xác suất SHORT/LONG cascade, signal paper trading, dashboard web real-time

---

## Kiến trúc 6 tầng (tất cả đã hoàn tất)

```
Binance Futures
     │
     ▼
Tầng 1 — collector/          ← 8 async streams → data/*.csv
     │
     ▼
Tầng 2 — feature_engine/     ← 46 features mỗi 1 phút → data/features_1m.csv
     │
     ▼
Tầng 3 — feature_engine/label_builder.py  ← điền cascade_short/long_Xm sau 1/2/3 phút
     │
     ▼
Tầng 4 — ml/train.py + auto_train.py     ← RandomForest, 6 models (3 horizons × SHORT+LONG)
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
| 1 | collector/ | ✅ running |
| 2 | feature_engine/ | ✅ running — 1 row/phút |
| 3 | label_builder.py | ✅ running — label 1/2/3m |
| 4 | ml/train.py, auto_train.py | ✅ running — retrain mỗi 1h |
| 5 | signal/ | ✅ running — threshold=0.60 |
| 6 | server/ (Django) | ✅ running |

**Giai đoạn hiện tại:** Paper trading để xác nhận live precision.
Mục tiêu: 20-30 trades có WIN/LOSS outcome → đánh giá live performance → live.

---

## Model — RandomForest

**Tại sao RF:** benchmark trên real data (5292 rows) — RF avg AUC 0.70 > LightGBM 0.67 > Ensemble(RF+LR+XGB) 0.66.
Platt scaling thử nghiệm → bị loại (max_prob ~0.12, không đạt threshold).

**6 models:** SHORT × {1,2,3}m + LONG × {1,2,3}m
Artifact: `ens_cascade_{direction}_{h}m.pkl` chứa `{"models": [rf], "imputer": ..., "model_names": ["RandomForest"]}`

**Kết quả thực tế @ threshold=0.60:**
- SHORT: AUC 1m=0.766 | Precision=93.1% | Recall=60.0% | F1=73.0%
- LONG:  AUC 1m=0.671 | Precision=95.6% | Recall=56.1% | F1=70.7%

**Signal condition:** max_prob(1m,2m,3m) >= SIGNAL_THRESHOLD (0.60 default, đọc từ .env)

---

## 46 Features

- Giá: price_change_1m/30s, volatility_1m, volume_1m, taker_buy_ratio
- Liquidation: liq_long/short_usd_1m, liq_total_1m, liq_ratio_1m, liq_accel_30s
- Order book: imbalance_now/avg_1m/trend, spread_now, bid_vol_now, ask_vol_now, wall_ratio, mid_price_now
- CVD futures: cvd_delta_1m/30s, whale_buy/sell_count/net, whale_buy/sell_usd_1m, whale_dominance
- Open interest: delta_oi_1m/30m/1h, oi_acceleration
- Funding: funding_rate, funding_rate_abs, funding_bias, funding_long/short_heavy, funding_rate_change, funding_trend_3h, secs_to_next_funding, funding_urgency
- Spot CVD: spot_cvd_delta_1m/30s
- Basis: basis_pct, basis_change_1m, basis_positive, cvd_divergence

---

## File structure quan trọng

```
collector/
  main.py              # asyncio entry — 8 coroutine song song
  ws_kline.py          # klines_1s.csv
  ws_liquidation.py    # liquidations.csv
  ws_orderbook.py      # orderbook.csv
  ws_aggtrade.py       # aggtrades.csv (futures CVD)
  ws_spot_aggtrade.py  # spot_aggtrades.csv
  rest_oi.py           # open_interest.csv (mỗi 30s)
  rest_funding.py      # funding_rate.csv (mỗi 1h)
  rest_basis.py        # basis.csv (futures-spot basis)
  db.py                # CSV append helper

feature_engine/
  run.py               # scheduler 1 phút
  build_features.py    # merge 46 features thành 1 row → features_1m.csv
  label_builder.py     # điền cascade_short/long_1m/2m/3m
  load_data.py         # CSV readers với timestamp parsing
  feat_price.py / feat_liquidation.py / feat_orderbook.py
  feat_aggtrade.py / feat_spot_aggtrade.py / feat_oi.py
  feat_funding.py / feat_basis.py

ml/
  train.py             # RandomForest (n=300, depth=10, balanced), 6 models
  auto_train.py        # loop: check labeled rows mỗi 1h → retrain nếu đủ data
  predict.py           # load_model(), predict_cascade_prob/signal/curve()
  artifacts/           # ens_cascade_*.pkl + meta.json (gitignored)

signal/
  run.py               # inference loop mỗi 1 phút
  paper_log.py         # log_signal() + check_outcomes() (WIN/LOSS/EXPIRED)
  notifier.py          # Telegram alert (opt-in)

scripts/
  monitor_short.py     # real-time SHORT signal monitor: TP/FP/FN + Prec/Recall/F1
                       # auto-reload model khi meta.json thay đổi
                       # chạy: make monitor
  rebuild_features.py  # rebuild features_1m.csv từ historical raw data
                       # dùng khi file bị corrupt/xóa
                       # chạy: make rebuild

server/
  btc_dashboard/settings.py   # Django settings
  btc_dashboard/asgi.py       # ProtocolTypeRouter
  dashboard/broadcaster.py    # push tick mỗi 1s qua WS group "tick"
  dashboard/consumers.py      # TickConsumer
  dashboard/data_reader.py    # CSV → dict
  dashboard/views.py          # /api/klines/ /api/signal/ /api/trades/ /api/liq/
  static/js/chart.js          # LightweightCharts (nến + liq zones)
  static/js/signal.js         # prob bar + countdown + curve
  templates/dashboard/index.html

docker/
  Dockerfile           # python:3.11-slim, single requirements.txt
  docker-compose.yml   # 5 services: collector, feature_engine, auto_train, signal, dashboard
```

---

## Data files (data/ — gitignored)

```
data/
  klines_1s.csv        # open_time, open, high, low, close, volume, taker_buy_vol, num_trades
  liquidations.csv     # event_time, symbol, side, price, qty, usd_value
  orderbook.csv        # timestamp, bid1..5_price/qty, ask1..5_price/qty, mid_price, spread, imbalance
  aggtrades.csv        # timestamp, agg_id, price, qty, usd_value, is_buyer_maker, cvd_delta
  spot_aggtrades.csv   # timestamp, ..., cvd_delta (spot)
  open_interest.csv    # timestamp, oi_btc, oi_usd
  funding_rate.csv     # timestamp, funding_rate, next_funding_time
  basis.csv            # timestamp, futures_price, spot_price, basis_pct
  features_1m.csv      # 46 features + cascade_short/long_1m/2m/3m labels
  paper_trades.csv     # opened_at, signal, prob, entry, tp, sl, rr, est_minutes,
                       # closed_at, outcome, pnl_pct, hit_tp, hit_sl
```

---

## Lệnh chạy

```bash
make setup         # venv + install deps
make tmux          # mở tất cả 6 services trong tmux session 'btc'
make status        # xem tmux session
make monitor       # SHORT signal monitor real-time
make rebuild       # rebuild features_1m.csv từ raw data (nếu bị corrupt)
make train         # train thủ công
make docker-up     # production Docker
make test          # tests
```

---

## Config (.env)

| Var | Default | Ghi chú |
|---|---|---|
| DJANGO_SECRET_KEY | — | bắt buộc |
| SIGNAL_THRESHOLD | 0.60 | precision ~93% SHORT, ~96% LONG |
| MIN_RR | 1.5 | R:R tối thiểu cho signal |
| MIN_ROWS_TRAIN | 200 | rows labeled để bắt đầu train |
| TELEGRAM_BOT_TOKEN | — | optional |
| TELEGRAM_CHAT_ID | — | optional |

---

## Lưu ý kỹ thuật

- `klines_1s.csv` dùng `now_utc()` cho timestamp (snapshot lúc ghi), không phải `open_time` của nến Binance
- `ws_orderbook.py` dùng `/stream?streams=btcusdt@depth20@500ms` — Binance wrap trong `{"stream":..., "data":...}`
- `broadcaster.py` thêm noise sin vào CVD khi không có collector (dev mode)
- Artifact bị corrupt nếu collector restart giữa chừng → rows bị merge → dùng `make rebuild`
- `auto_train.py` dùng `MIN_ROWS_TRAIN` từ config (không phải MIN_LABELED)
- `SIGNAL_THRESHOLD` đọc từ env tại runtime — không cần restart service, chỉ cần edit .env rồi restart

---

## Roadmap

- [ ] 2-3 tuần paper trading → xác nhận live precision/recall
- [ ] Calibrate TP/SL/window (hiện tại: 0.8%/0.5%/3min — tất cả đang EXPIRED)
- [ ] Walk-forward backtesting (nhiều splits thay vì 1 split 80/20)
- [ ] Live PnL thay paper trading
- [ ] Multi-symbol (ETH, SOL)
- [ ] Optuna hyperparameter tuning
