# BTC Cascade Liquidation Predictor

> Real-time ML system dự đoán BTC có xảy ra cascade liquidation trong 1/2/3 phút tới không.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![Model](https://img.shields.io/badge/model-RandomForest-orange.svg)](https://scikit-learn.org)
[![Django](https://img.shields.io/badge/backend-Django%20Channels-092E20.svg)](https://channels.readthedocs.io)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

---

## Overview

Hệ thống stream dữ liệu thật từ Binance Futures, tính 46 features mỗi 1 phút, và chạy RandomForest classifier để dự đoán khả năng xảy ra cascade liquidation. Khi xác suất vượt ngưỡng, signal được ghi vào paper trades.

**Kết quả thực tế trên dữ liệu thật (5 ngày Binance)**

| Metric | SHORT signal | LONG signal |
|---|---|---|
| AUC-ROC (1m) | 0.766 | 0.671 |
| Precision @ 0.60 | 93.1% | 95.6% |
| Recall @ 0.60 | 60.0% | 56.1% |
| F1 @ 0.60 | 73.0% | 70.7% |

---

## Architecture

```
Binance Futures WebSocket / REST
            │
            ▼
┌───────────────────┐
│   collector/      │  Layer 1 — 8 async streams → data/*.csv
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  feature_engine/  │  Layer 2+3 — 46 features mỗi 1 phút
│  label_builder    │             + label cascade_short/long_Xm
└────────┬──────────┘
         │  data/features_1m.csv
         ▼
┌───────────────────┐
│      ml/          │  Layer 4 — RandomForest (n=300, balanced)
│  train.py         │            6 models: SHORT/LONG × 1/2/3m
│  auto_train.py    │            auto-retrain mỗi 1h
└────────┬──────────┘
         │  ml/artifacts/ens_cascade_*_*m.pkl
         ▼
┌───────────────────┐
│    signal/        │  Layer 5 — inference + paper trading
└────────┬──────────┘
         │  data/paper_trades.csv
         ▼
┌───────────────────┐
│    server/        │  Layer 6 — Django + Channels WebSocket dashboard
└───────────────────┘
```

---

## Project Structure

```
btc-liq-predictor/
├── collector/              # Layer 1 — Binance WebSocket collectors
│   ├── main.py             #   Entry point (asyncio multi-stream)
│   ├── ws_kline.py         #   klines_1s.csv
│   ├── ws_liquidation.py   #   liquidations.csv
│   ├── ws_orderbook.py     #   orderbook.csv
│   ├── ws_aggtrade.py      #   aggtrades.csv (futures CVD)
│   ├── ws_spot_aggtrade.py #   spot_aggtrades.csv (spot CVD)
│   ├── rest_oi.py          #   open_interest.csv
│   ├── rest_funding.py     #   funding_rate.csv
│   ├── rest_basis.py       #   basis.csv (futures-spot basis)
│   └── db.py               #   CSV append helper
│
├── feature_engine/         # Layer 2+3 — Features + labels
│   ├── run.py              #   Loop mỗi 1 phút
│   ├── build_features.py   #   Merge 46 features thành 1 row
│   ├── label_builder.py    #   cascade_short/long_Xm labels
│   ├── load_data.py        #   CSV readers
│   └── feat_*.py           #   Per-source feature modules (8 files)
│
├── ml/                     # Layer 4 — Training & inference
│   ├── train.py            #   RandomForest, 6 models, time-split
│   ├── auto_train.py       #   Auto-retrain mỗi 1h
│   ├── predict.py          #   load_model() / predict_signal()
│   └── artifacts/          #   ens_cascade_*.pkl + meta.json (gitignored)
│
├── signal/                 # Layer 5 — Signal generation
│   ├── run.py              #   Inference loop mỗi 1 phút
│   ├── paper_log.py        #   Log + evaluate paper trades
│   └── notifier.py         #   Telegram alerts (optional)
│
├── server/                 # Layer 6 — Web dashboard
│   ├── btc_dashboard/      #   Django project (settings, asgi, urls)
│   ├── dashboard/          #   App: views, consumers, broadcaster
│   ├── static/             #   JS (LightweightCharts, Chart.js)
│   └── templates/
│
├── scripts/
│   ├── monitor_short.py    #   Real-time SHORT signal monitor (tmux)
│   └── rebuild_features.py #   Rebuild features_1m.csv từ raw data
│
├── notebooks/
│   └── model_selection.ipynb   # Benchmark: RF vs LightGBM vs Ensemble
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── data/                   # gitignored — generated at runtime
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml  # 5 services: collector, feature_engine,
│                           #   auto_train, signal, dashboard
├── config.py               # Single source of truth: paths + constants
├── .env.example
├── Makefile
└── pyproject.toml
```

---

## Quick Start

```bash
# 1. Setup
git clone <repo-url> && cd btc-liq-predictor
make setup
cp .env.example .env   # set DJANGO_SECRET_KEY

# 2. Chạy từng service (terminal riêng)
make collector         # thu thập data Binance
make features          # build features mỗi 1 phút
make auto-train        # retrain model mỗi 1h
make signal            # inference + paper trades
make server            # dashboard http://localhost:8000

# Hoặc dùng tmux (xem cả 5 service cùng lúc)
make tmux

# Hoặc Docker (production)
make docker-up
```

---

## Giám sát signal SHORT real-time

```bash
make monitor           # mở monitor trong tmux window hiện tại
```

Output mỗi 60 giây: bảng TP/FP/FN + Precision/Recall/F1 + tự reload model khi auto_train xong.

---

## ML Model

**Algorithm:** RandomForest (`n_estimators=300, max_depth=10, class_weight=balanced`)

**Benchmark:** RF avg AUC 0.70 > LightGBM 0.67 > Ensemble(RF+LR+XGB) 0.66 trên real data.  
Xem: [`notebooks/model_selection.ipynb`](notebooks/model_selection.ipynb)

**46 features:**

| Category | Features |
|---|---|
| Price | price_change_1m/30s, volatility_1m, volume_1m, taker_buy_ratio |
| Liquidation | liq_long/short_usd_1m, liq_total, liq_ratio, liq_accel_30s |
| Order book | imbalance_now/avg_1m/trend, spread, bid/ask_vol, wall_ratio |
| CVD futures | cvd_delta_1m/30s, whale_buy/sell_count/net/usd, whale_dominance |
| CVD spot | spot_cvd_delta_1m/30s, cvd_divergence |
| Basis | basis_pct, basis_change_1m, basis_positive |
| Open interest | delta_oi_1m/30m/1h, oi_acceleration |
| Funding | funding_rate, funding_bias, long/short_heavy, trend_3h, urgency |

**Label:**
- `cascade_short_Xm = 1` nếu `min(low[T → T+Xm]) ≤ liq_zone_lower`
- `cascade_long_Xm  = 1` nếu `max(high[T → T+Xm]) ≥ liq_zone_upper`

---

## Environment Variables

```bash
cp .env.example .env
```

| Variable | Required | Default | Mô tả |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | — | Django secret key |
| `SIGNAL_THRESHOLD` | No | 0.60 | Ngưỡng probability để bắn signal |
| `MIN_RR` | No | 1.5 | Tỷ lệ R:R tối thiểu |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram alert |
| `TELEGRAM_CHAT_ID` | No | — | Telegram chat ID |

---

## Commands

```bash
make status        # xem trạng thái tất cả services
make train         # train model thủ công
make monitor       # giám sát SHORT signal real-time
make rebuild       # rebuild features_1m.csv từ raw data
make test          # chạy test suite
make lint          # flake8
make clean         # xóa cache
```

---

## Docker

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml logs -f
```

5 services: `collector`, `feature_engine`, `auto_train`, `signal`, `dashboard`.

---

## Roadmap

- [ ] 2-3 tuần paper trading để xác nhận precision/recall trên live data
- [ ] Walk-forward backtesting (nhiều splits)
- [ ] Calibrate TP/SL/window cho paper trades (hiện tại: 0.8%/0.5%/3min)
- [ ] Live PnL thay thế paper trading
- [ ] Multi-symbol (ETH, SOL)
- [ ] Optuna hyperparameter tuning

---

## License

MIT
